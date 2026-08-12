\# NIK YouTube Capability Map

Status: INITIAL VERIFIED BASELINE

Date: 2026-08-12

Owner: NIK / Founder

\---

\## 1. Purpose

This document defines the currently known YouTube capabilities relevant to

NIK's operating system and Knowledge Operating System (KOS).

It distinguishes:

\- DOCUMENTED — capability confirmed in official Google documentation.

\- TESTED — NIK has successfully called the relevant API capability.

\- IMPLEMENTED — NIK has reusable production-oriented code for the capability.

\- APPROVED — explicitly approved for autonomous NIK operation.

\- DEFERRED — intentionally not being implemented yet.

These states must not be conflated.

\---

\## 2. Current NIK YouTube Authorization

Current OAuth scopes:

\- https://www.googleapis.com/auth/youtube.readonly

\- https://www.googleapis.com/auth/yt-analytics.readonly

Current authorization status:

\- OAuth authentication: TESTED

\- Persistent refresh token: TESTED

\- YouTube Data API access: TESTED

\- YouTube Analytics API access: TESTED

Write permissions are NOT currently authorized.

\---

\# 3. YouTube Data API

\## 3.1 Channel

Capability:

\- Retrieve channel metadata

\- Retrieve channel content details

\- Retrieve channel statistics

\- Retrieve branding settings

\- Retrieve status/topic/localization information where authorized

Status:

\- DOCUMENTED: YES

\- TESTED: YES

\- IMPLEMENTED: PARTIAL

\- APPROVED: READ ONLY

NIK relevance:

HIGH

Potential KOS use:

\- Channel identity

\- Channel metadata

\- Channel state snapshots

\- Provenance for channel-level observations

\---

\## 3.2 Videos

Capability:

\- Retrieve video metadata

\- Retrieve title and description

\- Retrieve publication information

\- Retrieve thumbnails

\- Retrieve tags/category information where available

\- Retrieve content details

\- Retrieve statistics

\- Retrieve status

\- Retrieve topic details where available

\- Retrieve live-stream information where applicable

Status:

\- DOCUMENTED: YES

\- TESTED: ENDPOINT YES / REAL VIDEO NO

\- IMPLEMENTED: PARTIAL

\- APPROVED: READ ONLY

Current NIK limitation:

The channel currently has zero published videos, so a real NIK video

resource has not yet been validated.

NIK relevance:

VERY HIGH

Potential KOS use:

\- Content identity

\- Content metadata

\- Content history

\- Performance observations

\- Content provenance

\---

\## 3.3 Uploaded Video Collection

YouTube exposes a channel's uploaded videos through the channel's

uploads playlist relationship.

Capability:

\- Discover uploads playlist

\- Retrieve playlist items

\- Resolve uploaded video IDs

Status:

\- DOCUMENTED: YES

\- TESTED: YES

\- IMPLEMENTED: PARTIAL

\- APPROVED: READ ONLY

NIK relevance:

VERY HIGH

Potential KOS use:

\- Canonical content inventory

\- Content ingestion

\- Historical content tracking

\---

\## 3.4 Playlists

Capability:

\- List playlists

\- Retrieve playlist metadata

\- Retrieve playlist items

\- Resolve video relationships

Status:

\- DOCUMENTED: YES

\- TESTED: YES

\- IMPLEMENTED: PARTIAL

\- APPROVED: READ ONLY

NIK relevance:

HIGH

Potential KOS use:

\- Content organization

\- Editorial collections

\- Content relationships

\---

\## 3.5 Comments

Capability:

\- Retrieve comment threads

\- Retrieve replies where available

\- Retrieve comment metadata

Status:

\- DOCUMENTED: YES

\- TESTED: NO

\- IMPLEMENTED: NO

\- APPROVED: READ ONLY

NIK relevance:

HIGH

Potential KOS use:

\- Audience feedback

\- Recurring questions

\- Audience language

\- Topic discovery

\- Qualitative audience evidence

No write/moderation capability is currently authorized.

\---

\## 3.6 Search

Capability:

\- Search videos

\- Search channels

\- Search playlists

Status:

\- DOCUMENTED: YES

\- TESTED: ENDPOINT YES

\- IMPLEMENTED: PARTIAL

\- APPROVED: CONTROLLED READ ONLY

NIK relevance:

MEDIUM / HIGH

Important:

Search is quota-sensitive and should NOT be exposed as an unrestricted

agent capability.

Use controlled search policies.

\---

\## 3.7 Activities

Capability:

\- Retrieve channel/user activity events

Status:

\- DOCUMENTED: YES

\- TESTED: NO

\- IMPLEMENTED: NO

\- APPROVED: NOT YET

Important:

The channel bulletin feature has been deprecated and activity insertion is

not supported.

NIK relevance:

MEDIUM

Potential use:

\- Historical activity signals

\- Event discovery

Decision:

DEFER until a concrete NIK requirement exists.

\---

\## 3.8 Subscriptions

Capability:

\- Retrieve authenticated user's subscriptions

Status:

\- DOCUMENTED: YES

\- TESTED: NO

\- IMPLEMENTED: NO

\- APPROVED: NOT YET

NIK relevance:

LOW for core KOS

Potential future use:

\- Research-source monitoring

\- Creator/channel watchlists

Decision:

DEFER until required.

\---

\# 4. YouTube Analytics API

\## 4.1 Targeted Reports

Capability:

\- Query metrics

\- Query dimensions

\- Apply filters

\- Specify date ranges

\- Analyze channel activity

\- Analyze video-level performance

\- Aggregate by supported dimensions

Status:

\- DOCUMENTED: YES

\- TESTED: YES

\- IMPLEMENTED: PARTIAL

\- APPROVED: READ ONLY

NIK relevance:

VERY HIGH

\---

\## 4.2 Core Analytics Dimensions

Documented core dimensions include:

\- ageGroup

\- channel

\- country

\- day

\- gender

\- month

\- sharingService

\- uploaderType

\- video

Additional supported dimensions exist.

NIK should implement only dimensions that correspond to actual

operational/KOS requirements.

\---

\## 4.3 Core Analytics Metrics

Documented core metrics include:

\- averageViewDuration

\- comments

\- dislikes

\- engagedViews

\- estimatedMinutesWatched

\- estimatedRevenue

\- likes

\- shares

\- subscribersGained

\- subscribersLost

\- viewerPercentage

\- views

Not all metrics should automatically become KOS knowledge.

A metric is an OBSERVATION.

A derived interpretation is a separate KNOWLEDGE CLAIM.

\---

\## 4.4 Analytics Data Model

NIK should preserve the distinction:

RAW OBSERVATION

&#x20; ->

NORMALIZED OBSERVATION

&#x20; ->

DERIVED ANALYSIS

&#x20; ->

KNOWLEDGE CLAIM

Do not collapse these into a single record.

\---

\# 5. YouTube Reporting API

Capability:

\- Schedule reporting jobs

\- Retrieve available bulk report types

\- Download generated reports

\- Process historical/bulk analytics datasets

Status:

\- DOCUMENTED: YES

\- TESTED: NO

\- IMPLEMENTED: NO

\- APPROVED: NOT YET

NIK relevance:

LOW NOW / HIGHER LATER

Decision:

DEFER.

Reason:

NIK currently has no meaningful historical channel volume and no demonstrated

need for bulk reporting.

Do not add this complexity merely because the API exists.

\---

\# 6. Quota Governance

NIK must treat YouTube API quota as a governed resource.

Important examples:

\- channels.list: low-cost read operation

\- videos.list: low-cost read operation

\- playlists.list: low-cost read operation

\- playlistItems.list: low-cost read operation

\- commentThreads.list: low-cost read operation

\- search.list: quota-sensitive

\- write operations: significantly more expensive

Agent rule:

NO AGENT MAY PERFORM UNBOUNDED SEARCH OR REPETITIVE API POLLING.

API access should eventually pass through a controlled NIK integration layer.

\---

\# 7. OAuth Security Boundary

Current authorized scopes are read-only.

NIK should NOT request write scopes simply because they exist.

Additional scopes must be introduced only when:

1\. A real NIK requirement exists.

2\. The capability is documented.

3\. The security impact is understood.

4\. The Founder explicitly approves the scope expansion.

Current state:

READ = ENABLED

WRITE = DISABLED

\---

\# 8. Capability State Model

Every YouTube capability should use this state model:

DOCUMENTED

&#x20; ↓

TESTED

&#x20; ↓

IMPLEMENTED

&#x20; ↓

APPROVED

&#x20; ↓

AUTOMATED

A capability must not silently skip states.

Example:

DOCUMENTED ≠ TESTED

TESTED ≠ IMPLEMENTED

IMPLEMENTED ≠ APPROVED

APPROVED ≠ AUTOMATED

\---

\# 9. KOS Boundary

YouTube is a SOURCE / SYSTEM OF RECORD.

It is not the KOS itself.

The intended relationship is:

YouTube

&#x20; ↓

NIK YouTube Integration

&#x20; ↓

Ingestion / Normalization

&#x20; ↓

Operational Data

&#x20; +

Knowledge Candidates

&#x20; ↓

KOS

KOS should retain provenance for durable knowledge.

At minimum, future knowledge records should be able to identify:

\- source system

\- source resource

\- source identifier

\- observation time

\- retrieval time

\- metric/dimension where applicable

\- transformation/derivation

\- confidence/status

\- original source reference

\---

\# 10. Agent Boundary

Agents should NOT receive unrestricted direct access to YouTube credentials.

Future architecture:

Agent

&#x20; ↓

NIK YouTube Capability Layer

&#x20; ↓

Authorized API operation

&#x20; ↓

YouTube

The capability layer should control:

\- allowed operations

\- scopes

\- quota

\- logging

\- retries

\- errors

\- provenance

\- rate limits

\---

\# 11. Current Verified Baseline

NIK channel:

Now I Know NIK

Current observed state:

\- Channel found: YES

\- Published videos: 0

\- Playlists returned: 0

\- Search results for own channel: 0

\- Subscribers: 0

\- Views: 0

These values are observations from the current channel state and must not

be treated as permanent facts.

Discovery artifact:

logs/youtube\_capability\_discovery.json

\---

\# 12. Current Implementation

Implemented:

\- OAuth authentication

\- Persistent token handling

\- YouTube Data API client access

\- YouTube Analytics API access

\- Channel discovery

\- Playlist discovery

\- Uploads playlist discovery

\- Basic video discovery

\- Basic search discovery

Not yet implemented:

\- reusable channel service

\- reusable video service

\- reusable playlist service

\- comment service

\- controlled search service

\- analytics service

\- reporting service

\- quota manager

\- provenance layer

\- Supabase persistence

\- Claude/MCP exposure

\- autonomous agents

\---

\# 13. Deliberate Deferrals

The following are intentionally NOT being implemented yet:

\- YouTube write operations

\- Video upload automation

\- Metadata modification

\- Playlist modification

\- Comment replies

\- Comment moderation

\- Channel updates

\- YouTube Reporting API

\- Advanced partner/content-owner capabilities

\- Monetization-specific access

\- Additional OAuth scopes

Future implementation requires an actual NIK requirement.

\---

\# 14. Next Phase

The next implementation phase is:

YOUTUBE CAPABILITY LAYER

Priority order:

1\. Channel service

2\. Video service

3\. Playlist service

4\. Comment read service

5\. Analytics service

6\. Controlled search service

7\. Quota governance

8\. Provenance model

9\. Tests

10\. NIK Automation integration

11\. KOS ingestion design

Do not connect Claude/MCP directly to raw credentials.

\---

\# 15. Governance Principle

The existence of an API capability does not create a requirement to implement it.

NIK implements capabilities because they serve an established operational,

editorial, research, or KOS requirement.

Avoid speculative infrastructure.

\---

END OF INITIAL CAPABILITY MAP
