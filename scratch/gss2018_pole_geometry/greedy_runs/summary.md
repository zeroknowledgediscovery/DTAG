## Summary (ΔJ after all steps)

| Persona | Push | J0 | Greedy mean ΔJ (3 runs) | Greedy runs ΔJ | Random mean ΔJ (30) [95% CI] | Greedy − random | one-sided steps | Audit: full-sweep choice in pool |
|---|---|---:|---:|---|---:|---:|---:|---|
| CM | right | +0.0263 | +0.0093 | +0.0591, -0.0074, -0.0238 | -0.0081 [-0.0149, -0.0010] | +0.0174 | 2/18 | coeduc (yes) |
| CM | left | +0.0263 | -0.0153 | -0.0080, -0.0371, -0.0008 | -0.0051 [-0.0122, +0.0017] | -0.0102 | 10/18 | abhlth (yes) |
| WF | right | -0.0358 | +0.0342 | +0.0804, +0.0163, +0.0059 | +0.0009 [-0.0071, +0.0089] | +0.0333 | 3/18 | heaven (yes) |
| WF | left | -0.0358 | -0.0364 | -0.0242, -0.0240, -0.0610 | +0.0092 [+0.0000, +0.0181] | -0.0456 | 4/18 | HUNT1 (yes) |

## Trajectories

### CM → right (J0 = +0.0263)

Greedy run 0:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | PRES12 — VOTE OBAMA OR ROMNEY | +0.0088 | 0.80 / 0.20 | romney (0.78) | +0.0123 | +0.0386 |
| 2 | PRES16 — VOTE TRUMP OR CLINTON | +0.0114 | 0.94 / 0.06 | iap (0.28) | +0.0002 | +0.0388 |
| 3 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | no (0.68) | -0.0000 | +0.0388 |
| 4 | rifle — RIFLE IN HOME (one-sided) | +0.0091 | 1.00 / 0.00 | no (0.74) | +0.0033 | +0.0421 |
| 5 | ABHELP3 — R WOULD HELP WITH PAYING FOR ABORTION-RELATED | +0.0070 | 0.60 / 0.40 | no (0.60) | +0.0256 | +0.0678 |
| 6 | ABHELP2 — R WOULD HELP WITH PAYING FOR ABORTION | +0.0149 | 0.95 / 0.05 | no (0.95) | +0.0177 | +0.0855 |

Greedy run 1:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | PRES12 — VOTE OBAMA OR ROMNEY | +0.0088 | 0.80 / 0.20 | obama (0.20) | -0.0045 | +0.0218 |
| 2 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | no (0.68) | -0.0000 | +0.0218 |
| 3 | rifle — RIFLE IN HOME (one-sided) | +0.0091 | 1.00 / 0.00 | no (0.74) | +0.0033 | +0.0251 |
| 4 | ABHELP3 — R WOULD HELP WITH PAYING FOR ABORTION-RELATED | +0.0078 | 0.60 / 0.40 | yes (0.40) | -0.0138 | +0.0113 |
| 5 | godmeans — LIFE MEANINGFUL BECAUSE GOD EXISTS | +0.0068 | 0.75 / 0.25 | neither agree nor disagree (0.20) | +0.0006 | +0.0119 |
| 6 | coeduc — HIGHEST YEAR SCHOOL COMPLETED, PARTNER | +0.0065 | 0.97 / 0.03 | e (0.88) | +0.0070 | +0.0189 |

Greedy run 2:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | PRES12 — VOTE OBAMA OR ROMNEY | +0.0088 | 0.80 / 0.20 | romney (0.78) | +0.0123 | +0.0386 |
| 2 | PRES16 — VOTE TRUMP OR CLINTON | +0.0114 | 0.94 / 0.06 | iap (0.28) | +0.0002 | +0.0388 |
| 3 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | refused (0.03) | +0.0051 | +0.0439 |
| 4 | godmeans — LIFE MEANINGFUL BECAUSE GOD EXISTS | +0.0069 | 0.75 / 0.25 | disagree (0.18) | -0.0071 | +0.0368 |
| 5 | homosex — HOMOSEXUAL SEX RELATIONS | +0.0094 | 0.34 / 0.66 | not wrong at all (0.57) | -0.0112 | +0.0257 |
| 6 | ABHELP3 — R WOULD HELP WITH PAYING FOR ABORTION-RELATED | +0.0078 | 0.60 / 0.40 | yes (0.40) | -0.0232 | +0.0025 |

Mean cumulative ΔJ by step (greedy vs random): t1: +0.0067 vs -0.0019; t2: +0.0068 vs -0.0037; t3: +0.0096 vs -0.0045; t4: +0.0038 vs -0.0066; t5: +0.0088 vs -0.0075; t6: +0.0093 vs -0.0081

### CM → left (J0 = +0.0263)

Greedy run 0:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | e (0.33) | -0.0116 | +0.0148 |
| 2 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM (one-sided) | -0.0064 | 0.00 / 1.00 | c (0.54) | -0.0001 | +0.0147 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0059 | 0.31 / 0.69 | morally opposed (0.31) | +0.0211 | +0.0357 |
| 4 | hunt — DOES R OR SPOUSE HUNT | -0.0046 | 0.19 / 0.81 | neither (0.79) | -0.0066 | +0.0291 |
| 5 | wrkstat — LABOR FORCE STATUS (one-sided) | -0.0044 | 0.00 / 1.00 | working fulltime (0.50) | -0.0042 | +0.0249 |
| 6 | visnhist — HOW OFTEN R VISITED NATURAL HISTORY MUSEUM LA (one-sided) | -0.0042 | 0.00 / 1.00 | e (0.45) | -0.0065 | +0.0184 |

Greedy run 1:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | e (0.33) | -0.0116 | +0.0148 |
| 2 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM (one-sided) | -0.0064 | 0.00 / 1.00 | e (0.45) | -0.0136 | +0.0011 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0059 | 0.31 / 0.69 | not morally opposed (0.26) | -0.0272 | -0.0260 |
| 4 | abinspay — SH OU LD PEOPLE BE AB L E TO USE HEA LT H INS | -0.0062 | 0.41 / 0.59 | people should not be able (0.41) | +0.0234 | -0.0026 |
| 5 | abfelegl — WOMEN ONLY: WOMEN SHOULD BE ABLE TO HAVE LEGA | -0.0091 | 0.45 / 0.55 | should not (0.15) | +0.0004 | -0.0022 |
| 6 | visnhist — HOW OFTEN R VISITED NATURAL HISTORY MUSEUM LA (one-sided) | -0.0049 | 0.00 / 1.00 | d (0.23) | -0.0086 | -0.0108 |

Greedy run 2:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | c (0.52) | -0.0043 | +0.0221 |
| 2 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM (one-sided) | -0.0064 | 0.00 / 1.00 | c (0.54) | -0.0001 | +0.0220 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0059 | 0.31 / 0.69 | morally opposed (0.31) | +0.0211 | +0.0430 |
| 4 | hunt — DOES R OR SPOUSE HUNT | -0.0046 | 0.19 / 0.81 | neither (0.79) | -0.0066 | +0.0364 |
| 5 | wrkstat — LABOR FORCE STATUS (one-sided) | -0.0044 | 0.00 / 1.00 | working parttime (0.11) | -0.0039 | +0.0325 |
| 6 | abhlth — WOMAN'S HEALTH SERIOUSLY ENDANGERED | -0.0043 | 0.10 / 0.90 | yes (0.90) | -0.0070 | +0.0255 |

Mean cumulative ΔJ by step (greedy vs random): t1: -0.0091 vs -0.0015; t2: -0.0137 vs -0.0030; t3: -0.0087 vs -0.0033; t4: -0.0054 vs -0.0050; t5: -0.0079 vs -0.0052; t6: -0.0153 vs -0.0051

### WF → right (J0 = -0.0358)

Greedy run 0:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | no (0.68) | -0.0000 | -0.0358 |
| 2 | rifle — RIFLE IN HOME (one-sided) | +0.0090 | 1.00 / 0.00 | no (0.74) | +0.0020 | -0.0338 |
| 3 | god — R'S CONFIDENCE IN THE EXISTENCE OF GOD | +0.0073 | 0.54 / 0.46 | know god exists (0.54) | +0.0243 | -0.0095 |
| 4 | coeduc — HIGHEST YEAR SCHOOL COMPLETED, PARTNER | +0.0068 | 0.97 / 0.03 | c (0.08) | +0.0082 | -0.0013 |
| 5 | homosex — HOMOSEXUAL SEX RELATIONS | +0.0035 | 0.34 / 0.66 | always wrong (0.34) | +0.0408 | +0.0395 |
| 6 | marhomo — HOMOSEXUALS SHOULD HAVE RIGHT TO MARRY | +0.0068 | 0.92 / 0.08 | agree (0.27) | +0.0051 | +0.0447 |

Greedy run 1:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | no (0.68) | -0.0000 | -0.0358 |
| 2 | rifle — RIFLE IN HOME (one-sided) | +0.0090 | 1.00 / 0.00 | no (0.74) | +0.0020 | -0.0338 |
| 3 | god — R'S CONFIDENCE IN THE EXISTENCE OF GOD | +0.0073 | 0.54 / 0.46 | no way to find out (0.07) | -0.0187 | -0.0525 |
| 4 | coeduc — HIGHEST YEAR SCHOOL COMPLETED, PARTNER | +0.0068 | 0.97 / 0.03 | e (0.88) | +0.0070 | -0.0455 |
| 5 | hell — BELIEF IN HELL | +0.0068 | 0.85 / 0.15 | yes, definitely (0.52) | +0.0105 | -0.0349 |
| 6 | heaven — BELIEF IN HEAVEN | +0.0098 | 0.81 / 0.19 | yes, definitely (0.81) | +0.0154 | -0.0195 |

Greedy run 2:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | pistol — PISTOL OR REVOLVER IN HOME | +0.0085 | 0.32 / 0.68 | no (0.68) | -0.0000 | -0.0358 |
| 2 | rifle — RIFLE IN HOME (one-sided) | +0.0090 | 1.00 / 0.00 | no (0.74) | +0.0020 | -0.0338 |
| 3 | god — R'S CONFIDENCE IN THE EXISTENCE OF GOD | +0.0073 | 0.54 / 0.46 | believe but doubts (0.18) | -0.0049 | -0.0387 |
| 4 | coeduc — HIGHEST YEAR SCHOOL COMPLETED, PARTNER | +0.0068 | 0.97 / 0.03 | c (0.08) | +0.0083 | -0.0304 |
| 5 | relpersn — R CONSIDER SELF A RELIGIOUS PERSON | +0.0066 | 0.53 / 0.47 | not religious (0.22) | -0.0060 | -0.0364 |
| 6 | hell — BELIEF IN HELL | +0.0066 | 0.85 / 0.15 | yes, probably (0.20) | +0.0065 | -0.0299 |

Mean cumulative ΔJ by step (greedy vs random): t1: -0.0000 vs -0.0011; t2: +0.0020 vs -0.0028; t3: +0.0022 vs -0.0017; t4: +0.0101 vs -0.0034; t5: +0.0252 vs +0.0000; t6: +0.0342 vs +0.0009

### WF → left (J0 = -0.0358)

Greedy run 0:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | c (0.52) | -0.0043 | -0.0400 |
| 2 | sprel — SPOUSE'S RELIGIOUS PREFERENCE | -0.0074 | 0.28 / 0.72 | none (0.41) | -0.0168 | -0.0569 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0061 | 0.31 / 0.69 | morally opposed (0.31) | +0.0206 | -0.0363 |
| 4 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM | -0.0055 | 0.54 / 0.46 | e (0.45) | -0.0120 | -0.0484 |
| 5 | miracles — BELIEF IN RELIGIOUS MIRACLES | -0.0050 | 0.18 / 0.82 | no, definitely not (0.30) | -0.0080 | -0.0564 |
| 6 | visnhist — HOW OFTEN R VISITED NATURAL HISTORY MUSEUM LA (one-sided) | -0.0042 | 0.00 / 1.00 | e (0.47) | -0.0036 | -0.0600 |

Greedy run 1:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | c (0.52) | -0.0043 | -0.0400 |
| 2 | sprel — SPOUSE'S RELIGIOUS PREFERENCE | -0.0074 | 0.28 / 0.72 | catholic (0.21) | -0.0005 | -0.0405 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0062 | 0.31 / 0.69 | it depends (0.43) | -0.0124 | -0.0530 |
| 4 | ABSTATE2 — ABORTION | -0.0058 | 0.27 / 0.73 | make it harder (0.27) | +0.0131 | -0.0399 |
| 5 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM | -0.0055 | 0.54 / 0.46 | e (0.45) | -0.0119 | -0.0518 |
| 6 | miracles — BELIEF IN RELIGIOUS MIRACLES | -0.0048 | 0.18 / 0.82 | no, definitely not (0.30) | -0.0080 | -0.0598 |

Greedy run 2:

| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |
|---:|---|---:|---|---|---:|---:|
| 1 | MAOCC10 — MOTHERS CENSUS OCCUPATION CODE (2010) (one-sided) | -0.0077 | 0.00 / 1.00 | c (0.52) | -0.0043 | -0.0400 |
| 2 | sprel — SPOUSE'S RELIGIOUS PREFERENCE | -0.0074 | 0.28 / 0.72 | catholic (0.21) | -0.0005 | -0.0405 |
| 3 | abmoral — R HAS A MORAL OPPOSITION TO ABORTION | -0.0062 | 0.31 / 0.69 | it depends (0.43) | -0.0124 | -0.0530 |
| 4 | ABSTATE2 — ABORTION | -0.0058 | 0.27 / 0.73 | make it easier (0.19) | -0.0176 | -0.0706 |
| 5 | abinspay — SH OU LD PEOPLE BE AB L E TO USE HEA LT H INS | -0.0093 | 0.32 / 0.68 | people should be able (0.68) | -0.0263 | -0.0968 |
| 6 | vissci — HOW OFTEN R VISITED SCIENCE MUSEUM | -0.0055 | 0.54 / 0.46 | c (0.54) | +0.0000 | -0.0968 |

Mean cumulative ΔJ by step (greedy vs random): t1: -0.0043 vs +0.0004; t2: -0.0102 vs +0.0000; t3: -0.0116 vs +0.0009; t4: -0.0172 vs +0.0034; t5: -0.0325 vs +0.0063; t6: -0.0364 vs +0.0092
