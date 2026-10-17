
# AML Prototype Investigation Policy

This document describes demonstration detection rules.
It is not a regulatory policy or a substitute for compliance review.

## Banking Detection Rules

### R001 — High-Value Banking Transaction
Condition: Banking transaction amount >= USD 25,000.
Risk points: 40.

### R002 — Customer Transaction Velocity
Condition: At least 5 transactions for the same customer
within 24 hours, including the current transaction.
Risk points: 30.

### R003 — Potential Structuring Pattern
Condition: At least 3 customer transactions between
USD 8,000 and USD 9,999.99 within 24 hours.
Risk points: 45.

This is a screening heuristic, not evidence that
structuring occurred.

## Bitcoin Detection Rules

### BTC001 — Large Bitcoin Transaction
Condition: Total transaction outputs >= 5 BTC.
Risk points: 25.

Total Bitcoin outputs can include change returned to
the spending wallet. The value does not necessarily
represent a payment to another person.

### BTC002 — Repeated Address Activity
Condition: An input address appears in at least
5 observed transactions within 24 hours.
Risk points: 20.

Shared addresses do not establish customer identity.

### BTC003 — Historical Amount Anomaly
Condition: At least 5 earlier related observations
exist, and current total output BTC is at least
3 times the historical median.
Risk points: 25.

### BTC004 — Multiple Bitcoin Outputs
Condition: At least 10 outputs in a transaction.
Risk points: 15.

Multiple outputs can result from legitimate batch
payments and exchange activity.

## Alert Policies

Banking:
Generate a review alert when risk score >= 30.

Bitcoin:
Generate a review alert only when at least 3
risk factors trigger AND the score >= 60.

Scores are screening priorities, not probabilities
of fraud or proof of money laundering.

## Investigation Guidance

An analyst should:
1. Verify the transaction identifier and source.
2. Review all triggered rules and their evidence.
3. Examine transaction history and relevant context.
4. Identify limitations in the available data.
5. Document findings before changing case status.

A transaction must not be described as criminal
solely because an automated rule was triggered.
