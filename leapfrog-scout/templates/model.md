# Data model (model_to_sql.py format)
# Types: text int bool time date json money enum(a,b) -> Entity  (append ? for nullable)
# owner user  adds user_id with a foreign key to users.
# Put evidence and confidence in comments.

entity User
  email text
  name text?

entity EventType
  owner user
  title text
  minutes int
  price money?

entity Booking
  # evidence: S09 form, help article "Cancel a booking". confidence: high
  event_type -> EventType
  start_at time
  end_at time
  guest_email text
  status enum(confirmed,cancelled,rescheduled)
  answers json
