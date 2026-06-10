# Fight Outcome Model Research

## Goal

Build a model that returns `P(fighter_a wins)` and `P(fighter_b wins)` for two
fighters already present in the warehouse.

The betting layer is separate. This phase should optimize prediction quality,
calibration, and diagnosability before comparing against market odds.

## Current Local Data

The current point-in-time feature surface is `pit_matchup_features`, built from
canonical warehouse tables. It contains one row per fight with red/blue fighter
features and deltas.

Current size and recency:

- `17,487` matchup rows.
- UFCStats latest event date: `2026-06-06`.
- Sherdog latest event date: `2026-06-06`.

Current feature groups:

- Prior record: fights, wins, losses, draws, no-contests.
- Layoff and age: days since previous fight, age at event date.
- Physical: height and reach.
- Method history: prior wins by KO/TKO, submission, decision.
- Performance history: fight time, significant strikes landed/absorbed,
  takedowns landed/attempted, submission attempts, control time.

Feature coverage differs sharply by source:

- Sherdog has useful broad fight history but sparse reach and detailed stats.
- UFCStats has strong bio and detailed stat coverage.

## Critical Data Risk

Do not train directly on `red_won` without neutralizing side assignment.

Observed corner win rates:

- Sherdog red corner win rate: `98.45%`.
- UFCStats red corner win rate: `63.03%`.

Sherdog is effectively winner-first in the current participant ordering. A model
that sees red/blue side semantics will learn source/parser structure instead of
fighter ability. UFCStats also has a red-corner assignment effect large enough to
make naive accuracy misleading.

The model dataset must therefore use one of these approaches:

- Randomize fighter order deterministically per fight and define the label as
  `fighter_a_won`.
- Or emit both orientations for each fight, with deltas negated for the swapped
  row and labels inverted.

The first option is simpler for training. The second option is useful as an
invariance test and may stabilize linear models.

## Literature Notes

### UFC Machine Learning Baselines

McQuaide's Stanford CS229 project used UFCStats pre-fight features and compared
generalized linear models, multilayer perceptrons, decision trees, and gradient
boosting. The study reports roughly 60% test accuracy and explicitly notes that
red-corner win rate alone can be a dangerous benchmark. This supports starting
with simple baselines and time-aware validation before adding model complexity.

Source: https://cs229.stanford.edu/proj2019aut/data/assignment_308832_raw/26647731.pdf

### Logistic and Bayesian Regression

The KTH thesis "Predicting UFC matches using regression models" used UFC data
from April 2000 through mid-April 2024 and compared logistic regression with
Bayesian regression. It reports 60% accuracy for logistic regression and 70% for
the Bayesian model, with predictions comparable to betting sites.

This supports two ideas for this repo:

- Logistic regression is the correct first baseline because it is transparent,
  cheap, and calibratable.
- Bayesian or hierarchical models are attractive later because fighter data is
  sparse and uncertainty matters.

Source: https://kth.diva-portal.org/smash/get/diva2%3A1878726/FULLTEXT01.pdf

### Fighter Style Features

The MLISE 2024 paper derives fighter style factors with factor analysis, clusters
fighters with K-means, and compares Random Forest, SVM, XGBoost, Logistic
Regression, Neural Networks, and majority-vote ensembles. It reports 65.52%
accuracy for majority voting and an ablation drop when style factors are removed.

This is useful, but style features should not be the first implementation here.
They depend on detailed stat coverage, which is strong for UFCStats but sparse
for Sherdog.

Source: https://jjthehonest.github.io/files/MLISE2024.pdf

### Pairwise Rating Models

Whole-History Rating is a Bayesian rating method for time-varying strength in
paired comparisons. It is based on a dynamic Bradley-Terry model and is designed
for competitors whose ability changes over time.

This is a natural baseline and feature source for fight prediction:

- produce each fighter's pre-fight strength estimate;
- use rating difference as a compact matchup feature;
- compare against richer PIT statistical models;
- keep ratings point-in-time to avoid leakage.

Source: https://www.remi-coulom.fr/WHR/

## Recommended Modeling Path

## Probability Contract

The production API should expose a binary complement:

- `p_fighter_a_wins = p`
- `p_fighter_b_wins = 1 - p`

That means the model should produce one scalar probability for the ordered pair
`(fighter_a, fighter_b)`, not two independent probabilities.

Preferred implementation:

```text
logit = f(features_a_minus_b)
p_fighter_a_wins = sigmoid(logit)
p_fighter_b_wins = 1 - p_fighter_a_wins
```

For swapped inputs, the ideal behavior is:

```text
f(features_b_minus_a) = -f(features_a_minus_b)
```

Linear logistic regression on pure delta features has this anti-symmetry
naturally. Tree/ensemble models do not guarantee it automatically, so they need
swapped-row training and an explicit swapped-input invariance test.

## SOTA Read

For MMA-specific literature, the strongest published modeling direction appears
to be simulation over fight states rather than plain binary classification.
Holmes, McHale, and Zychaluk estimate fighter skills for key MMA dimensions and
simulate the contest with a Markov chain. Their benchmarks include Bayesian
Bradley-Terry and logistic regression on cumulative-stat differences.

Source: https://prod-dcd-datasets-public-files-eu-west-1.s3.eu-west-1.amazonaws.com/05bdcbd7-50e1-4f75-95e5-693192fd2708

For paired competition more generally, dynamic Bradley-Terry/Elo-family models
remain difficult baselines to beat on sparse sports data. Kiraly and Qian connect
Elo to Bradley-Terry and supervised online learning; Coulom's Whole-History
Rating is a Bayesian time-varying strength model for paired comparisons.

Sources:

- https://arxiv.org/abs/1701.08055
- https://www.remi-coulom.fr/WHR/

For tabular MMA machine learning, recent work favors engineered differential
features, opponent-quality/strength-of-schedule adjustment, style factors, and
ensembles such as logistic regression, random forest, SVM, XGBoost, neural nets,
and soft/majority voting. This is useful as a later comparison, but the current
repo should first solve leakage, side bias, calibration, and source missingness.

Sources:

- https://jjthehonest.github.io/files/MLISE2024.pdf

### 1. Model Dataset Builder

Create a reproducible dataset command or module that joins:

- `pit_matchup_features`;
- fight labels from `fight_participants` or `fights`;
- event date, source, promotion, and later weight/gender fields when available.

MVP target:

- binary `fighter_a_won`;
- exclude draws and no-contests;
- deterministic order randomization or paired swapped rows;
- no post-fight columns beyond the label.

The builder should write a derived table or parquet file and a short metadata
report with row counts, date range, excluded rows, feature missingness, and label
balance.

### 2. Baselines

Start with baselines that can expose leakage and data defects:

- majority class by source and year;
- regularized logistic regression on delta features;
- rating-only model using Elo/Glicko-style or Bradley-Terry-style pre-fight
  ratings;
- logistic regression combining PIT deltas and pre-fight rating deltas.

These should be scored before gradient boosting.

### 3. Tree Model

After the dataset and baselines pass leakage checks, add a gradient-boosted tree
model. Prefer a conservative implementation first:

- scikit-learn `HistGradientBoostingClassifier` if dependency simplicity matters;
- XGBoost or LightGBM later if the repo accepts the dependency.

Use missingness indicators and source-aware evaluation because Sherdog and
UFCStats have very different feature coverage.

For the probability contract, tree models should be called in one ordered
direction and the reverse probability should be computed as `1 - p`, not by
running a separate reverse prediction. A swapped-input test should still verify
that `model(A, B) + model(B, A)` is close to `1`.

### 4. Calibration

The product output is probability, not only class prediction. Evaluate and
calibrate probabilities:

- log loss;
- Brier score;
- calibration curves by time period and source;
- expected calibration error if useful.

Accuracy and AUC are secondary.

### 5. Later Research Tracks

Add these only after the MVP is stable:

- Bayesian hierarchical model for fighter uncertainty and shrinkage.
- Fighter style factors and clusters from detailed stat history.
- Promotion/source/weight-class interaction effects.
- Odds ingestion and market-efficiency analysis.

## Validation Rules

Use temporal splits only. Do not use random train/test splits for the main score.

Minimum split policy:

- train on older fights;
- validate on a later contiguous window;
- test on the newest held-out window.

Core checks:

- no same-date/current-fight leakage;
- labels align to the selected fighter orientation;
- swapped-row invariance holds;
- draw/no-contest handling is explicit;
- source-stratified metrics are reported;
- calibration is reported, not just accuracy.

## Immediate Implementation Questions

1. Should MVP train on UFCStats only, or train on UFCStats plus Sherdog with
   source-aware missingness and metrics?
2. Should the first dataset use deterministic randomized orientation or emit both
   orientations?
3. What is the first acceptable held-out test window: last 12 months, last 24
   months, or a fixed date cutoff?
4. Should rating features be built before or after the first logistic baseline?
