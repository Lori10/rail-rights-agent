# quality-gates Specification

## Purpose

Defines the offline checks every change must pass before it can merge, the same locally and in CI, and keeps live or billed calls out of them.

## Requirements

### Requirement: The check script runs every offline gate
The repository's check script SHALL run each of these gates and fail if any of them fails:
- lint
- format check
- strict type check over application and infrastructure source
- the offline test suite
- OpenSpec validation
- the secret scan where available

#### Scenario: All gates pass
- **WHEN** the check script runs on a tree that is lint-clean, formatted, type-correct, with passing tests and valid specs
- **THEN** it exits with status 0 and reports PASS for each gate

#### Scenario: A type error fails the run
- **WHEN** the check script runs on a tree containing a type error in application or infrastructure source
- **THEN** the type-check gate reports FAIL
- **AND** the script exits with a non-zero status

#### Scenario: Unformatted code fails the run
- **WHEN** the check script runs on a tree containing a Python file that does not match the configured formatter
- **THEN** the format gate reports FAIL
- **AND** the script exits with a non-zero status

### Requirement: CI runs the same check script on every PR and on main
The CI workflow SHALL run the check script on every pull request and on every push to the protected branch. Dependencies SHALL be installed from the committed lockfile.

#### Scenario: Pull request opened
- **WHEN** a pull request is opened or updated
- **THEN** the required `checks` job installs dependencies from the lockfile and runs the check script

### Requirement: Offline gates never call live or billed services
The default test run and the check script SHALL NOT require AWS credentials and SHALL NOT call AWS or any other paid API. Tests that need live services SHALL be excluded from the default run and only run when explicitly selected.

#### Scenario: Default run without credentials
- **WHEN** the default test run executes with no AWS credentials and no AWS configuration
- **THEN** it completes without errors caused by missing credentials

#### Scenario: Live test excluded by default
- **WHEN** a test is marked as live and the default test run executes
- **THEN** that test is not run
