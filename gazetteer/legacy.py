"""metadata for collections published outside this pipeline, filled in where their own files leave it empty.

erddap-places' `places` collection (catalog/build_places.R there) has no place_type column, no gazetteer:* keys
in collection.json and the portolan default title "Places", so its index rows showed an empty type and the site
credited a sanctuary to a layer called "Places". The values here are used only when the published data has none:
a place_type column or a real title written at the source wins, and this table then does nothing.
"""
from __future__ import annotations

LEGACY = {
  "places": {
    "title"     : "erddap-places statistics places (18 NOAA sanctuaries, Pitcairn EEZ, Tortugas reserve)",
    # by place_id prefix; each prefix is one kind of place in this collection
    "place_type": {"NMS": "protected_area", "PSGID": "protected_area", "MRGID": "eez"},
  },
}


def legacy_title(slug: str, title: str | None) -> str | None:
  """the title for a layer: its own, unless it is missing or a default made from the slug ("places", "Places")."""
  meta = LEGACY.get(slug)
  if not meta or (title and title.strip().lower() not in {slug.lower(), slug.replace("_", " ").lower()}):
    return title
  return meta["title"]


def legacy_place_type(slug: str, place_id: str | None) -> str | None:
  """the place_type of a row of a legacy collection from its place_id prefix, else None."""
  meta = LEGACY.get(slug)
  if not meta or not place_id or ":" not in place_id:
    return None
  return meta["place_type"].get(place_id.split(":", 1)[0])
