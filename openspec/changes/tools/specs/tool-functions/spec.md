# Spec Delta

## Purpose

Defines the contract every tool function follows when hosted as a Lambda, so the same handlers serve the local agent now and the AgentCore Gateway later without change.

## ADDED Requirements

### Requirement: One function per tool, arguments in, JSON out
Each tool (`get_train_delay`, `calculate_compensation`, `submit_claim`) SHALL be its own Lambda function. The function SHALL take the tool's arguments as the event object, as the AgentCore Gateway passes them, and SHALL return a JSON-serialisable object.

#### Scenario: Compensation handler
- **WHEN** the compensation handler is invoked with the arguments of a €100 single ticket and a 60-minute delay
- **THEN** it returns an object whose compensation is `25.00` and whose references and token are present

### Requirement: Optional arguments may be null or omitted
A handler SHALL treat an optional argument given as JSON null the same as an omitted one, and SHALL accept a whole number given as an integral float (such as 60.0).

#### Scenario: Null optionals
- **WHEN** the compensation handler is invoked with `travel_class` and `cause` set to null
- **THEN** it uses the defaults (2nd class, unknown cause) and returns a result, not an error

### Requirement: Errors are returned as structured results, never raised
When a tool rejects its input or finds nothing, the handler SHALL return an object with an `error` holding a `code` and a `message`, instead of raising. Service failures, connection failures and unreadable stored records SHALL be returned the same way with a stable code.

#### Scenario: Unknown trip through the handler
- **WHEN** the delay handler is invoked for a train and date with no record
- **THEN** it returns an `error` with code `TRIP_NOT_FOUND` and a message naming the train and date

#### Scenario: Service failure
- **WHEN** the store rejects a request with a service error
- **THEN** the handler returns an `error` whose code is the service's error code

### Requirement: Functions get only the access they need
The delay function SHALL only read the trips table, the submission function SHALL only read and write items of the claims table, and the compensation function SHALL have no table access. No function policy SHALL grant access to all resources.

#### Scenario: Synthesise function policies
- **WHEN** the infrastructure app is synthesised
- **THEN** the delay function's policy names only the trips table with read actions, the submission function's policy names only the claims table with get and put actions, and the compensation function has no table statement
- **AND** no statement in the tools stack has resource `*`

### Requirement: Functions are small, short-lived and leave nothing behind
Each function SHALL run Python 3.12, SHALL time out within 10 seconds, and SHALL log to a log group that the stack owns, with retention of 7 days and deletion on destroy. Table names SHALL reach the functions through environment variables.

#### Scenario: Synthesise functions
- **WHEN** the infrastructure app is synthesised
- **THEN** each of the three functions declares the Python 3.12 runtime, a timeout of at most 10 seconds, and a stack-owned log group with 7-day retention and a delete deletion policy

### Requirement: The tools stack exposes its ids
The tools stack SHALL output the trips table name, the claims table name and the ARN of each of the three functions.

#### Scenario: Stack outputs
- **WHEN** the tools stack is synthesised
- **THEN** it declares outputs for both table names and the three function ARNs

### Requirement: Live tools behave end to end
Against the deployed and seeded stack, invoking the three functions SHALL return the seeded delay, the computed compensation and a stored claim, and a second identical submission SHALL return the same claim id marked already submitted.

#### Scenario: Live round trip
- **WHEN** the live test looks up a seeded 120-minute delay, computes compensation for a €100 single ticket on it and submits the claim twice
- **THEN** the delay is 120, the payout is €50.00, the first submission is stored and the second returns the same claim id marked already submitted
