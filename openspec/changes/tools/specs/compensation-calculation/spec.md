# Spec Delta

## Purpose

Computes delay compensation deterministically from Art. 19 of Regulation (EU) 2021/782 and the DB conditions of carriage, and returns the legal references and a confirmation token with every result, so the agent explains and cites but never calculates.

## ADDED Requirements

### Requirement: Compensation percentage follows Art. 19(1)
For a single ticket, the calculation SHALL award 0 % for a delay under 60 minutes, 25 % of the ticket price for 60 to 119 minutes, and 50 % for 120 minutes or more. The delay is the arrival delay at the final destination in whole minutes.

#### Scenario: 45 minutes
- **WHEN** compensation is computed for a €100 single ticket and a 45-minute delay
- **THEN** the result is not eligible, the percentage is 0 and the reason is that the delay is below 60 minutes

#### Scenario: 60 minutes
- **WHEN** compensation is computed for a €100 single ticket and a 60-minute delay
- **THEN** the result is eligible with 25 % and a compensation of €25.00

#### Scenario: 119 minutes
- **WHEN** compensation is computed for a €100 single ticket and a 119-minute delay
- **THEN** the compensation is €25.00

#### Scenario: 120 minutes
- **WHEN** compensation is computed for a €100 single ticket and a 120-minute delay
- **THEN** the result is eligible with 50 % and a compensation of €50.00

### Requirement: Return tickets count at half price
When the ticket is a return ticket without a separately indicated price for the delayed leg, the calculation SHALL use half of the price paid as the base (Art. 19(3)).

#### Scenario: Delay on one leg of a return ticket
- **WHEN** compensation is computed for a €100 return ticket and a 130-minute delay
- **THEN** the base price is €50.00 and the compensation is €25.00

### Requirement: Amounts are rounded to cents and small amounts are not paid
The compensation SHALL be rounded half-up to cents (DB A.9.2.1). When the rounded compensation is below €4.00, the result SHALL state the computed compensation but a payout of €0.00 and the reason that it is below the minimum payout (DB A.9.2.1, Art. 19(8)).

#### Scenario: Rounding
- **WHEN** compensation is computed for a €29.90 single ticket and a 60-minute delay
- **THEN** the compensation is €7.48 (25 % of 29.90 is 7.475, rounded half-up)

#### Scenario: Below the minimum payout
- **WHEN** compensation is computed for a €12.00 single ticket and a 75-minute delay
- **THEN** the compensation is €3.00, the payout is €0.00 and the reason is the minimum payout
- **AND** no confirmation token is issued

#### Scenario: Exactly the minimum payout
- **WHEN** compensation is computed for a €16.00 single ticket and a 60-minute delay
- **THEN** the compensation and the payout are both €4.00 and a confirmation token is issued

### Requirement: Exclusions under Art. 19(9), 19(1) and 19(10)
The calculation SHALL return no compensation, with a reason and reference naming the rule, when the passenger was informed of the delay before buying (Art. 19(9)), the ticket was already reimbursed under Art. 18 (Art. 19(1)), or the cause is extraordinary circumstances (19(10)(a)), passenger fault (19(10)(b)) or third-party behaviour (19(10)(c)).

#### Scenario: Extreme weather
- **WHEN** compensation is computed for a 150-minute delay whose cause is extreme weather
- **THEN** the result is not eligible and its references include Art. 19(10)(a)

#### Scenario: Persons on the track
- **WHEN** compensation is computed for a 150-minute delay whose cause is third-party behaviour
- **THEN** the result is not eligible and its references include Art. 19(10)(c)

#### Scenario: Informed before purchase
- **WHEN** compensation is computed for a 150-minute delay and the passenger was informed of it before buying
- **THEN** the result is not eligible and its references include Art. 19(9)

#### Scenario: Already reimbursed
- **WHEN** compensation is computed for a 150-minute delay on a ticket already reimbursed under Art. 18
- **THEN** the result is not eligible and its references include Art. 19(1)

### Requirement: Strikes and infrastructure failures remain compensable
A delay caused by a strike of the railway undertaking's own staff, by the infrastructure or station manager, or by ordinary operational causes SHALL be compensable (Art. 19(10), last sentence). An unknown cause SHALL be treated as compensable, because the burden of proof lies with the railway.

#### Scenario: Own-staff strike
- **WHEN** compensation is computed for a €100 single ticket, a 120-minute delay and the cause "own-staff strike"
- **THEN** the compensation is €50.00

#### Scenario: Unknown cause
- **WHEN** compensation is computed for a €100 single ticket, a 60-minute delay and an unknown cause
- **THEN** the compensation is €25.00

### Requirement: Flat rates for long-distance season tickets and BahnCard 100
For a long-distance season ticket (ICE or IC/EC Zeitkarte), a delay of 60 minutes or more SHALL yield €5.00 in 2nd class and €7.50 in 1st class (DB B.13.1). For a BahnCard 100, it SHALL yield €10.00 in 2nd class and €15.00 in 1st class (DB C.3.10.1). The amount for one case SHALL be capped at 25 % of the ticket price, and the result SHALL note that the cap applies to all cases in the validity period.

#### Scenario: Season ticket, 2nd class
- **WHEN** compensation is computed for a long-distance season ticket, 2nd class, priced €400, with a 70-minute delay
- **THEN** the compensation is €5.00 and its references include DB B.13.1

#### Scenario: BahnCard 100, 1st class
- **WHEN** compensation is computed for a BahnCard 100, 1st class, priced €7000, with a 200-minute delay
- **THEN** the compensation is €15.00 and its references include DB C.3.10.1

#### Scenario: Season ticket below 60 minutes
- **WHEN** compensation is computed for a long-distance season ticket with a 59-minute delay
- **THEN** the result is not eligible

#### Scenario: Cap at 25 % of the ticket price
- **WHEN** compensation is computed for a long-distance season ticket, 2nd class, priced €16, with a 70-minute delay
- **THEN** the compensation is €4.00 (25 % of €16, below the €5.00 flat rate)

### Requirement: Deutschland-Ticket and regional season tickets are not computed
For a Deutschland-Ticket or a regional season ticket, the calculation SHALL return a result that is not computable from the source documents, with a reference to DB C.3.10.3 (Deutschland-Ticket rights follow its own tariff), and no amount or token.

#### Scenario: Deutschland-Ticket
- **WHEN** compensation is computed for a Deutschland-Ticket with a 90-minute delay
- **THEN** the result is marked not computable, its references include DB C.3.10.3 and no token is issued

### Requirement: Every result carries structured legal references
Every result SHALL list the references it rests on, each as a source document id matching the knowledge-base catalogue (`eu-2021-782` or `db-befoerderungsbedingungen`) and an article or clause label. An eligible single-ticket result SHALL reference at least Art. 19(1) and DB A.9.2.1.

#### Scenario: References on an eligible result
- **WHEN** compensation is computed for a €100 single ticket and a 60-minute delay
- **THEN** the references include (`eu-2021-782`, Art. 19(1)(a)) and (`db-befoerderungsbedingungen`, A.9.2.1)

### Requirement: A confirmation token binds the amount to its inputs
When the payout is above zero, the result SHALL include a confirmation token derived deterministically from the inputs and the payout. The same inputs SHALL always produce the same token, and a change to any input that affects the amount SHALL produce a different token.

#### Scenario: Same inputs, same token
- **WHEN** compensation is computed twice with identical inputs
- **THEN** both results carry the same token

#### Scenario: Different price, different token
- **WHEN** compensation is computed for a €100 and for a €101 ticket, otherwise identical
- **THEN** the two tokens differ

### Requirement: Invalid inputs are rejected
The calculation SHALL reject a negative, zero, non-finite or implausibly large ticket price, a negative delay, a travel class other than 1 or 2, and an unknown ticket kind or cause, with an error naming the invalid field.

#### Scenario: Negative delay
- **WHEN** compensation is computed with a delay of -5 minutes
- **THEN** it fails with an error naming the delay

#### Scenario: Zero price
- **WHEN** compensation is computed with a ticket price of €0
- **THEN** it fails with an error naming the price

#### Scenario: Non-finite price
- **WHEN** compensation is computed with a ticket price of NaN or infinity
- **THEN** it fails with an error naming the price

### Requirement: Compensation properties hold for all inputs
For every valid single-ticket input: the compensation SHALL never exceed 50 % of the price rounded half-up to cents, SHALL not decrease when only the delay increases, and the payout SHALL be either €0.00 or at least €4.00.

#### Scenario: Property check over generated inputs
- **WHEN** the calculation runs over many generated prices and delays
- **THEN** every result satisfies the three properties above
