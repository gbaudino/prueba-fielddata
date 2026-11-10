#!/usr/bin/env bash
set -Eeuo pipefail

API_URL="${API_URL:-http://localhost:8000}"
API_URL="${API_URL%/}"
ALERT_THRESHOLD=70

log() {
  printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

fail() {
  printf '\n\033[1;31mERROR: %s\033[0m\n' "$1" >&2
  exit 1
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$field"
}

count_alert_notifications() {
  local response="$1"
  local alert_id="$2"
  python3 -c '
import json, sys
payload = json.load(sys.stdin)
alert_id = sys.argv[1]
print(sum(item["alert_id"] == alert_id for item in payload["items"]))
' "$alert_id" <<< "$response"
}

find_notification_id() {
  local response="$1"
  local alert_id="$2"
  local forecast_date="$3"
  python3 -c '
import json, sys
payload = json.load(sys.stdin)
alert_id, forecast_date = sys.argv[1:]
matches = [
    item for item in payload["items"]
    if item["alert_id"] == alert_id
    and item["forecast_date"] == forecast_date
]
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one notification for {forecast_date}; "
        f"found {len(matches)}"
    )
print(matches[0]["id"])
' "$alert_id" "$forecast_date" <<< "$response"
}

for command in curl docker python3 make; do
  command -v "$command" >/dev/null 2>&1 || fail "Required command not found: $command"
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."

log "Waiting for API readiness"
API_READY=false
for attempt in {1..30}; do
  if curl --silent --fail "$API_URL/health/ready" >/dev/null; then
    API_READY=true
    break
  fi
  sleep 1
done
[[ "$API_READY" == true ]] || fail \
  "API did not become ready at $API_URL. Check: docker compose logs api"
printf 'API is ready: %s\n' "$API_URL"

log "Selecting a seeded user, field and forecast"
DEMO_CASE="$(docker compose exec -T db sh -c '
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -At -F "|" -c "
    SELECT
      u.id,
      f.id,
      wf.event_type,
      wf.probability,
      wf.forecast_date
    FROM users AS u
    JOIN fields AS f ON u.id = ANY(f.related_users)
    JOIN weather_forecasts AS wf ON wf.field_id = f.id
    LEFT JOIN alerts AS a
      ON a.user_id = u.id
      AND a.field_id = f.id
      AND a.event_type = wf.event_type
    WHERE a.id IS NULL
      AND wf.forecast_date >= (now() AT TIME ZONE f.timezone)::date
      AND wf.probability >= 80
    ORDER BY wf.probability DESC, wf.forecast_date ASC
    LIMIT 1;
  "
')"

[[ -n "$DEMO_CASE" ]] || fail \
  "No eligible forecast found. Run 'make start' to initialize the demo data."

IFS='|' read -r USER_ID FIELD_ID EVENT_TYPE PROBABILITY FORECAST_DATE \
  <<< "$DEMO_CASE"

printf 'User:           %s\n' "$USER_ID"
printf 'Field:          %s\n' "$FIELD_ID"
printf 'Event:          %s\n' "$EVENT_TYPE"
printf 'Forecast:       %s%% on %s\n' "$PROBABILITY" "$FORECAST_DATE"
printf 'Alert threshold: %s%%\n' "$ALERT_THRESHOLD"

log "Creating alert"
ALERT_RESPONSE="$(curl --silent --show-error --fail-with-body \
  -X POST "$API_URL/v1/alerts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  --data "{\
    \"field_id\": \"$FIELD_ID\",\
    \"event_type\": \"$EVENT_TYPE\",\
    \"threshold\": $ALERT_THRESHOLD\
  }")"

ALERT_ID="$(json_field id <<< "$ALERT_RESPONSE")"
printf '%s\n' "$ALERT_RESPONSE" | python3 -m json.tool
printf '\nCreated alert: %s\n' "$ALERT_ID"

log "Checking duplicate alert protection"
DUPLICATE_STATUS="$(curl --silent --show-error \
  -o /dev/null -w '%{http_code}' \
  -X POST "$API_URL/v1/alerts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  --data "{\
    \"field_id\": \"$FIELD_ID\",\
    \"event_type\": \"$EVENT_TYPE\",\
    \"threshold\": $ALERT_THRESHOLD\
  }")"
[[ "$DUPLICATE_STATUS" == "409" ]] || fail \
  "Expected duplicate alert to return 409; got $DUPLICATE_STATUS"
printf 'Duplicate alert correctly rejected with HTTP 409.\n'

log "Listing alerts for the user"
curl --silent --show-error --fail \
  "$API_URL/v1/alerts?field_id=$FIELD_ID" \
  -H "X-User-Id: $USER_ID" \
  | python3 -m json.tool

run_evaluation() {
  docker compose run --rm --no-deps worker \
    python -m agroclimate.worker --once
}

log "Running the first alert evaluation"
run_evaluation

log "Finding the generated notification"
NOTIFICATIONS="$(curl --silent --show-error --fail \
  "$API_URL/v1/notifications?unread=true&field_id=$FIELD_ID&limit=100" \
  -H "X-User-Id: $USER_ID")"
NOTIFICATION_ID="$(find_notification_id \
  "$NOTIFICATIONS" "$ALERT_ID" "$FORECAST_DATE")"
BEFORE_COUNT="$(count_alert_notifications "$NOTIFICATIONS" "$ALERT_ID")"
printf 'Notifications generated for this alert: %s\n' "$BEFORE_COUNT"
printf 'Notification for %s: %s\n' "$FORECAST_DATE" "$NOTIFICATION_ID"

log "Running evaluation again to verify idempotency"
run_evaluation
NOTIFICATIONS_AFTER="$(curl --silent --show-error --fail \
  "$API_URL/v1/notifications?unread=true&field_id=$FIELD_ID&limit=100" \
  -H "X-User-Id: $USER_ID")"
AFTER_COUNT="$(count_alert_notifications \
  "$NOTIFICATIONS_AFTER" "$ALERT_ID")"

[[ "$BEFORE_COUNT" == "$AFTER_COUNT" ]] || fail \
  "Idempotency failed: $BEFORE_COUNT notifications became $AFTER_COUNT"
printf 'Idempotency OK: %s notifications before and after the second run.\n' \
  "$AFTER_COUNT"

log "Marking the notification as read"
READ_RESPONSE="$(curl --silent --show-error --fail-with-body \
  -X POST "$API_URL/v1/notifications/read" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  --data "{\"notification_ids\":[\"$NOTIFICATION_ID\"]}")"
printf '%s\n' "$READ_RESPONSE" | python3 -m json.tool

log "Verifying it is no longer unread"
UNREAD_AFTER_READ="$(curl --silent --show-error --fail \
  "$API_URL/v1/notifications?unread=true&field_id=$FIELD_ID&limit=100" \
  -H "X-User-Id: $USER_ID")"

python3 -c '
import json, sys
payload = json.load(sys.stdin)
notification_id = sys.argv[1]
if any(item["id"] == notification_id for item in payload["items"]):
    raise SystemExit("Notification is still unread")
' "$NOTIFICATION_ID" <<< "$UNREAD_AFTER_READ"

printf '\n\033[1;32mDemo completed successfully.\033[0m\n'
printf 'Alert ID:        %s\n' "$ALERT_ID"
printf 'Notification ID: %s\n' "$NOTIFICATION_ID"
printf 'User ID:         %s\n' "$USER_ID"
