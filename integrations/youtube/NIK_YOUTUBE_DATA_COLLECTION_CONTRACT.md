\# NIK YouTube Data Collection Contract



\*\*Version:\*\* 1.0

\*\*Status:\*\* Foundation

\*\*System:\*\* NIK YouTube Integration



\---



\## 1. Purpose



This contract defines how the NIK YouTube integration collects,

stores, and preserves data obtained from YouTube APIs.



The purpose is to create a reliable historical record that can later

support:



\- channel analysis

\- video analysis

\- performance analysis

\- trend detection

\- change detection

\- research

\- NIK operating intelligence



This layer records observed data.



It does not make strategic conclusions.



\---



\## 2. Core Principle



The system must distinguish between:



1\. OBSERVED DATA

2\. DERIVED DATA

3\. INTERPRETATION

4\. ASSUMPTION



Only observed data is stored as primary evidence from the YouTube API.



Derived calculations may be produced later from observed data.



Interpretations and assumptions must never be silently stored as facts.



\---



\## 3. Source of Truth



For YouTube channel and performance data:



YouTube APIs are the primary external source.



The local snapshot is the historical record of what the API returned

at the time of collection.



A later API response must not overwrite an earlier snapshot.



Historical snapshots are append-only.



\---



\## 4. Snapshot Types



The system currently supports:



\### 4.1 Channel Snapshot



Snapshot type:



`youtube\_channel`



Purpose:



Record the current structural state of the channel.



Examples:



\- channel ID

\- channel title

\- description

\- custom URL

\- publication date

\- country

\- subscriber count

\- view count

\- video count

\- uploads playlist ID

\- available branding information



\---



\### 4.2 Video Inventory Snapshot



Snapshot type:



`youtube\_video\_inventory`



Purpose:



Record which videos exist in the channel's uploads playlist.



Examples:



\- video ID

\- title

\- description

\- publication date

\- playlist position

\- channel information

\- video status

\- available video details

\- available statistics



An empty inventory is valid.



An empty result must not be treated as an API failure.



\---



\### 4.3 Channel Analytics Snapshot



Snapshot type:



`youtube\_channel\_analytics`



Purpose:



Record channel-level performance for a defined reporting period.



Examples:



\- views

\- estimated minutes watched

\- average view duration

\- subscribers gained

\- subscribers lost

\- likes

\- comments

\- shares



Every analytics snapshot must record:



\- reporting start date

\- reporting end date

\- generation timestamp

\- channel ID

\- metrics requested

\- raw API response



\---



\## 5. Historical Preservation



Snapshots are immutable after creation.



The system must not:



\- overwrite previous snapshots

\- silently replace historical values

\- delete snapshots as part of normal collection

\- merge different reporting periods into one record



Each collection produces a new timestamped record.



\---



\## 6. Storage



Local operational data is stored under:



`data/`



Current structure:



```text

data/

├── analytics/

└── snapshots/

&#x20;   ├── channel/

&#x20;   └── videos/