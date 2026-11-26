# Spec Delta

## Purpose

Answers "how late was this train" from a store of mock trip records, giving the agent the delay, status and cause category it needs before computing compensation.

## ADDED Requirements

### Requirement: A delay record is found by train number and travel date
Given a train number and a travel date, the lookup SHALL return the matching trip record: train number, travel date, origin, destination, scheduled departure and arrival, actual arrival (absent when cancelled), delay in whole minutes, status (`on_time`, `delayed` or `cancelled`) and cause category.

#### Scenario: Delayed train
- **WHEN** the lookup is asked for a seeded train that arrived 75 minutes late
- **THEN** it returns that record with status `delayed`, delay 75 and its cause category

#### Scenario: Cancelled train
- **WHEN** the lookup is asked for a seeded cancelled train
- **THEN** it returns status `cancelled`, no actual arrival, and the delay the passenger incurred reaching the destination with the replacement service

### Requirement: Train numbers are matched leniently
The lookup SHALL ignore case and spaces in the train number, so `ice 123`, `ICE123` and `ICE 123` find the same record.

#### Scenario: Lower case with a space
- **WHEN** the lookup is asked for `ice 123` on a date that has an `ICE 123` record
- **THEN** it returns that record

### Requirement: Unknown trips and invalid dates are reported as errors
When no record exists for the train and date, the lookup SHALL return a not-found error naming both. A travel date that is not a valid calendar date in `YYYY-MM-DD` form SHALL be rejected before the store is read.

#### Scenario: Unknown trip
- **WHEN** the lookup is asked for a train and date with no record
- **THEN** it returns a not-found error that names the train number and the date

#### Scenario: Invalid date
- **WHEN** the lookup is asked with the date `2026-13-40`
- **THEN** it fails with an error naming the date, without reading the store

### Requirement: The seed data covers every compensation rule
The seed data set SHALL contain fixed trips, with fixed dates, that include at least: an on-time train, delays of 45, 60, 119, 120 and over 180 minutes, a cancelled train, and one trip for each cause category (operational, own-staff strike, infrastructure, extreme weather, third party). Loading the seed data SHALL be repeatable without creating duplicates.

#### Scenario: Seed data contents
- **WHEN** the seed data set is inspected
- **THEN** it contains records for each of the listed delays, statuses and cause categories

#### Scenario: Seeding twice
- **WHEN** the seed command runs twice against the same store
- **THEN** the store holds each seeded trip exactly once

### Requirement: The trips store is pay-per-use and disposable
The trips store SHALL be an on-demand table keyed by normalised train number and travel date, with no idle cost, encrypted at rest, and deleted when its stack is destroyed.

#### Scenario: Synthesise the trips table
- **WHEN** the infrastructure app is synthesised
- **THEN** the tools stack contains a table in on-demand billing mode, keyed by train number (partition) and travel date (sort), with a delete deletion policy
