\# NIK YouTube Snapshot Schema



\## Purpose



Define the canonical structure for capturing the current state of the

Now I Know NIK YouTube channel.



This is a data contract, not an analytics interpretation.



\---



\## 1. Snapshot Metadata



\- snapshot\_id

\- snapshot\_type

\- generated\_at\_utc

\- source

\- api\_version

\- channel\_id



\## 2. Channel Identity



\- channel\_id

\- title

\- description

\- custom\_url

\- published\_at

\- country

\- thumbnails



\## 3. Channel Statistics



\- view\_count

\- subscriber\_count

\- video\_count



\## 4. Channel Content



\- uploads\_playlist\_id

\- uploads\_playlist\_item\_count



\## 5. Videos



For each video:



\- video\_id

\- channel\_id

\- title

\- description

\- published\_at

\- channel\_title

\- tags

\- category\_id

\- live\_broadcast\_content

\- duration

\- dimension

\- definition

\- caption

\- licensed\_content

\- projection

\- view\_count

\- like\_count

\- comment\_count

\- thumbnails

\- privacy\_status

\- embeddable

\- public\_stats\_viewable



\## 6. Analytics



For the requested reporting period:



\- start\_date

\- end\_date

\- views

\- estimated\_minutes\_watched

\- average\_view\_duration

\- likes

\- comments

\- shares

\- subscribers\_gained

\- subscribers\_lost



\## 7. Retrieval Metadata



\- retrieved\_resources

\- pagination\_completed

\- errors

\- warnings



\## 8. Evidence



Every snapshot must preserve:



\- retrieval timestamp

\- source API

\- resource type

\- resource ID

\- raw API response where appropriate



\---



\## Implementation Note \(added 2026-08-12, provenance pass\)



Field names as actually implemented: \`source\` is \`"youtube\_data\_api"\` or \`"youtube\_analytics\_api"\`; \`api\_version\` is \`"v3"\` or \`"v2"\`. §7 Retrieval Metadata is nested under a \`retrieval\_metadata\` key. §8's raw response lives under \`evidence.raw\_response\` for the channel snapshot; the analytics snapshot's existing \`analytics\` field already is the full raw response, so it is not duplicated under a second key. \`pagination\_completed\` is \`null\` for a single-call, non-paginated retrieval \(channel, analytics\) rather than \`true\`, so it can't be misread as "pagination was attempted and finished." \`errors\` and \`warnings\` are present per this schema but will be empty under the current architecture — a failed API call currently raises an exception and prevents a snapshot from being written at all, rather than producing a partial snapshot with a recorded error. Populating them meaningfully is future work, not done in this pass.
