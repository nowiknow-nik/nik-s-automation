"""
NIK YouTube evidence ingestion adapters (B2.3.2+).

Reads JSON already written by the acquisition scripts (channel_snapshot.py,
and later video_inventory.py / analytics_snapshot.py) and inserts it into
the corresponding youtube_evidence table in Supabase, losslessly and
idempotently. Never modifies an acquisition script, never issues UPDATE
or DELETE against an evidence table, and never reaches Supabase through
the Data API -- youtube_evidence is deliberately not exposed there.

See NIK_YOUTUBE_B2_3_2_CHANNEL_SNAPSHOT_INGESTION_DESIGN.md for the full
design this package implements.
"""
