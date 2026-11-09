# Fictional evaluator calibration

Authored synthetic challenge pairs. These results measure these fixtures only.
Evaluator 2; selected threshold 0.8.
Representation and threshold use development data only.

| Mode | Correctly flagged | Missed bad output | False alarm | Correctly accepted |
|---|---:|---:|---:|---:|
| holdout | 9 | 3 | 4 | 8 |
| holdout_cosine_only | 5 | 7 | 4 | 8 |

## Every held-out error

- **paraphrase — false_positive**. Equivalent payment outcome in this fixture.
  Reference: The payment was declined.
  Candidate: The transaction was rejected.
- **double-negative — false_positive**. Equivalent under the fixture's binary approved/declined contract.
  Reference: The refund was approved.
  Candidate: The refund was not declined.
- **thousands — false_positive**. Equivalent thousands formatting.
  Reference: The export contains 2000 records.
  Candidate: The export contains 2,000 records.
- **synonym — false_positive**. Equivalent status in this fixture.
  Reference: The account is active.
  Candidate: The account is enabled.
- **entity-swap — false_negative**. Reverses payer and payee.
  Reference: Alice paid Bob.
  Candidate: Bob paid Alice.
- **scope-swap — false_negative**. Negation count is equal but scope changes.
  Reference: Alice was approved and Bob was not.
  Candidate: Bob was approved and Alice was not.
- **word-number — false_negative**. Changes a spelled-out number.
  Reference: Three teams restored 8 backups.
  Candidate: Four teams restored 8 backups.

Negation counts cannot resolve scope or antonyms. Lexical similarity can reject valid paraphrases. Use task-specific assertions or a calibrated judge for those contracts.

Development SHA-256 85a0d258b7bea67d70200bfe0a4c00f3b799bc2898b929b8f785c3347620f374
Holdout SHA-256 c1420f6fdb889227d6836e5d595855c40f2a29fcccebbc2386fc91631b5613eb
