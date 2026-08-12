\# NIK YouTube Change Detection Contract



\*\*Version:\*\* 1.0

\*\*Status:\*\* Foundation

\*\*System:\*\* NIK YouTube Integration



\---



\## 1. Purpose



This contract defines how the NIK YouTube integration compares

historical observations and records changes between them.



The purpose is to transform:



OBSERVATION A + OBSERVATION B



into:



OBSERVED CHANGE



without silently converting the change into an interpretation.



\---



\## 2. Core Principle



Change detection records what changed.



It does not explain why the change happened.



Example:



Observed:



\- subscribers changed from 0 to 25

\- views changed from 0 to 1,240

\- videos changed from 0 to 3



Derived change:



\- subscribers: +25

\- views: +1,240

\- videos: +3



Interpretation:



\- channel experienced growth



Causal conclusion:



\- a particular video caused the growth



The first two layers may be produced by this system.



Interpretation and causal conclusions belong to later analytical layers.



\---



\## 3. Evidence Classes



Every change must remain distinguishable as one of:



\### OBSERVED



Directly returned by YouTube.



\### DERIVED



Calculated from observed values.



\### INTERPRETATION



A conclusion about the meaning of observed or derived values.



\### ASSUMPTION



A statement that is not established by the available evidence.



The change-detection layer must produce OBSERVED and DERIVED data only.



\---



\## 4. Comparison Requirements



A comparison requires two valid observations:



```text

previous

current