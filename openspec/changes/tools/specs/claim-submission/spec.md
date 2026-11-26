# Spec Delta

## Purpose

Records a compensation claim exactly once, only for an amount that was computed by the compensation rules and confirmed, and keeps the claims store as the single source of truth for past claims.

## ADDED Requirements

### Requirement: A claim needs a matching confirmation token
Submission SHALL recompute the compensation from the claim's trip and ticket fields and accept the claim only if the given confirmation token equals the token of that result. Otherwise it SHALL reject the claim with an error saying the confirmation does not match, without writing anything.

#### Scenario: Matching token
- **WHEN** a claim is submitted with the token from the matching compensation result
- **THEN** the claim is stored and the response carries a claim id and the payout amount

#### Scenario: Missing token
- **WHEN** a claim is submitted with an empty token
- **THEN** it is rejected before the store is touched

#### Scenario: Token for different inputs
- **WHEN** a claim is submitted with a token computed for a different ticket price
- **THEN** it is rejected with a confirmation-mismatch error and nothing is stored

### Requirement: Nothing to claim is rejected
When the recomputed result has a payout of €0.00 (not eligible, below the minimum payout or not computable), submission SHALL reject the claim with the result's reason and store nothing.

#### Scenario: Below the minimum payout
- **WHEN** a claim is submitted for a €12 ticket and a 75-minute delay
- **THEN** it is rejected with the minimum-payout reason and nothing is stored

### Requirement: Submission is idempotent
A claim id SHALL be derived from the confirmation token together with the train number, travel date and passenger email, so the same confirmed claim always maps to the same id and two different passengers or trips with equal amounts never share one. Submitting a claim whose id already exists SHALL store nothing and return the existing claim, marked as already submitted.

#### Scenario: Second submission of the same claim
- **WHEN** the same claim is submitted twice
- **THEN** the second response carries the same claim id, is marked already submitted, and the store still holds one record

#### Scenario: Equal amounts for different passengers
- **WHEN** two claims with identical ticket and delay fields are submitted for different trips or by passengers with different emails
- **THEN** they get different claim ids

### Requirement: Claim fields are validated
Submission SHALL require a non-empty passenger name and a contact email containing `@`, and SHALL accept an optional IBAN. Invalid fields SHALL be rejected with an error naming the field, before the store is touched.

#### Scenario: Missing name
- **WHEN** a claim is submitted with an empty passenger name
- **THEN** it is rejected with an error naming the passenger name

### Requirement: The stored claim is complete
A stored claim SHALL hold: claim id, confirmation token, train number, travel date, ticket kind, travel class, ticket price, delay minutes, cause, compensation and payout amounts, passenger name, email, IBAN when given, status `submitted`, and the submission time in UTC.

#### Scenario: Stored record
- **WHEN** a claim is stored
- **THEN** the written record contains every field above with the submitted values

### Requirement: The claims store is pay-per-use and disposable
The claims store SHALL be an on-demand table keyed by claim id, with no idle cost, encrypted at rest, and deleted when its stack is destroyed.

#### Scenario: Synthesise the claims table
- **WHEN** the infrastructure app is synthesised
- **THEN** the tools stack contains a table in on-demand billing mode keyed by claim id with a delete deletion policy
