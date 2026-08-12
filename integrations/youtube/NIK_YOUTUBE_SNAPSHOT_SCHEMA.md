\# NIK YouTube Snapshot Schema



\## Purpose



Define the canonical structure for capturing the current state of the

Now I Know NIK YouTube channel.



This is a data contract, not an analytics interpretation.



\---



\## 1. Snapshot Metadata



\- snapshot\_id

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
