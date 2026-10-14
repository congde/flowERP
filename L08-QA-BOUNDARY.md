# L08 isolated maintainer CI fixture

This branch deliberately injects a premature commit into SalesService.reserve.
The frozen product Eval now covers multiline success, second-line shortage and
an injected second-write failure, including all four persisted tables.

A and B must use the identical product SHA. C only removes the labelled premature
commit, retaining all checks. This fixture does not authorize a main-branch merge,
represent a customer incident, or provide a student/named-human acceptance.
