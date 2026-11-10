"""Mapeo generado desde db.json — NO editar a mano.

Regenerar con: python3 tools/generate_schema_map.py

Contiene las 32 tablas del esquema "public" de PostgreSQL/Supabase.
"""

# Columnas válidas por tabla (validación de payloads de POST/PATCH).
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "audit_logs": ("id", "actor_id", "action", "entity", "entity_id", "details", "created_at"),
    "business_verifications": ("id", "business_id", "responsible_name", "contact_email", "document_path", "status", "reviewer_id", "review_notes", "reviewed_at", "created_at"),
    "businesses": ("id", "owner_id", "name", "contact_email", "phone", "created_at"),
    "campaign_events": ("id", "campaign_id", "kind", "occurred_at", "created_at"),
    "campaigns": ("id", "business_id", "title", "ad_text", "placement", "budget", "starts_at", "ends_at", "zone_id", "category_id", "radius_meters", "status", "created_at"),
    "categories": ("id", "name", "slug", "created_at"),
    "coupon_redemptions": ("id", "user_id", "promotion_id", "idempotency_key", "savings", "redeemed_at", "created_at"),
    "experiences": ("id", "business_id", "place_id", "title", "description", "starts_at", "price_per_person", "capacity", "vip_only", "published", "created_at"),
    "moderation_actions": ("id", "review_id", "moderator_id", "action", "reason", "created_at"),
    "notifications": ("id", "user_id", "title", "body", "kind", "ticket_id", "read_at", "created_at"),
    "offline_downloads": ("id", "user_id", "route_id", "snapshot", "version", "created_at"),
    "opening_hours": ("id", "place_id", "weekday", "opens_at", "closes_at", "created_at"),
    "place_categories": ("id", "place_id", "category_id", "created_at"),
    "place_media": ("id", "place_id", "storage_path", "kind", "position", "created_at"),
    "place_visits": ("id", "user_id", "place_id", "visited_at", "created_at"),
    "places": ("id", "business_id", "zone_id", "name", "description", "address", "latitude", "longitude", "estimated_cost", "visit_minutes", "services", "published", "created_at"),
    "profiles": ("id", "full_name", "avatar_url", "phone", "terms_accepted_at", "home_lat", "home_lng", "created_at"),
    "promotions": ("id", "business_id", "place_id", "title", "code", "discount_percent", "starts_at", "ends_at", "max_redemptions", "per_user_limit", "conditions", "status", "created_at"),
    "reservations": ("id", "user_id", "experience_id", "participants", "total", "status", "idempotency_key", "created_at"),
    "review_media": ("id", "review_id", "storage_path", "created_at"),
    "review_replies": ("id", "review_id", "business_id", "body", "created_at"),
    "reviews": ("id", "user_id", "place_id", "rating", "body", "hidden", "created_at"),
    "route_stops": ("id", "route_id", "place_id", "position", "arrival_at", "visit_minutes", "travel_minutes", "travel_meters", "estimated_cost", "created_at"),
    "routes": ("id", "user_id", "name", "budget", "available_minutes", "origin_lat", "origin_lng", "zone_id", "category_id", "preference", "visibility", "share_slug", "created_at"),
    "saved_routes": ("id", "user_id", "route_id", "visited_at", "created_at"),
    "subscription_plans": ("id", "name", "price", "currency", "period_days", "created_at"),
    "subscriptions": ("id", "user_id", "plan_id", "starts_at", "ends_at", "status", "created_at"),
    "ticket_messages": ("id", "ticket_id", "sender_id", "body", "attachment_path", "created_at"),
    "tickets": ("id", "user_id", "place_id", "route_id", "redemption_id", "review_id", "subject", "description", "kind", "priority", "status", "assigned_to", "created_at"),
    "user_access": ("id", "user_id", "role", "status", "created_at"),
    "user_interests": ("id", "user_id", "category_id", "created_at"),
    "zones": ("id", "name", "city", "country_code", "latitude", "longitude", "created_at"),
}

# Columnas FK por tabla (filtros permitidos en listas GET).
FOREIGN_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "audit_logs": ("actor_id",),
    "business_verifications": ("business_id", "reviewer_id"),
    "businesses": ("owner_id",),
    "campaign_events": ("campaign_id",),
    "campaigns": ("business_id", "category_id", "zone_id"),
    "coupon_redemptions": ("promotion_id", "user_id"),
    "experiences": ("place_id", "business_id"),
    "moderation_actions": ("moderator_id", "review_id"),
    "notifications": ("ticket_id", "user_id"),
    "offline_downloads": ("route_id", "user_id"),
    "opening_hours": ("place_id",),
    "place_categories": ("category_id", "place_id"),
    "place_media": ("place_id",),
    "place_visits": ("place_id", "user_id"),
    "places": ("business_id", "zone_id"),
    "promotions": ("place_id", "business_id"),
    "reservations": ("experience_id", "user_id"),
    "review_media": ("review_id",),
    "review_replies": ("business_id", "review_id"),
    "reviews": ("place_id", "user_id"),
    "route_stops": ("place_id", "route_id"),
    "routes": ("category_id", "user_id", "zone_id"),
    "saved_routes": ("route_id", "user_id"),
    "subscriptions": ("plan_id", "user_id"),
    "ticket_messages": ("sender_id", "ticket_id"),
    "tickets": ("assigned_to", "place_id", "redemption_id", "review_id", "route_id", "user_id"),
    "user_access": ("user_id",),
    "user_interests": ("category_id", "user_id"),
}

# Columnas gestionadas por la base de datos: nunca llegan en payloads.
READONLY_COLUMNS: frozenset[str] = frozenset((
    "id",
    "created_at",
))

TABLE_COUNT: int = 32
