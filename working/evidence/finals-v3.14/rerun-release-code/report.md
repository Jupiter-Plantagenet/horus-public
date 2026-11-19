# HORUS v3 evaluation — twin v2, opencellid map, seeds 2200..2259 (n=60 per cell, PRE-REGISTERED HELD-OUT)

Generated 2026-11-19T04:06:48Z at commit e228d84. All arms on identical radio traces per (cell, seed), run in one sim pass per trace. Means with 95% t-CIs over episodes.

## Pre-registered go/no-go (finals_preregistration_v3.json): **H2**

### H1_oracle: FAIL
- vs `a3_tuned`: PASS
  - PASS utility: pooled 95% CI of (v3 - a3_tuned) > 0: diff +0.2256 [+0.1967, +0.2545]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.3647 and no Holm-significant cell increase beyond it: diff -0.9250 [-0.9923, -0.8577]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0334 [-0.0378, -0.0289]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0011 [-0.0021, -0.0002]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0071 [-0.0081, -0.0061]
- vs `cho_tuned`: PASS
  - PASS utility: pooled 95% CI of (v3 - cho_tuned) > 0: diff +0.0092 [+0.0025, +0.0159]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.3073 and no Holm-significant cell increase beyond it: diff -0.3508 [-0.3751, -0.3265]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0025 [+0.0018, +0.0032]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0025 [+0.0018, +0.0031]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0000 [-0.0001, +0.0001]
- vs `cho_tuned_ext`: FAIL
  - FAIL utility: pooled 95% CI of (v3 - cho_tuned_ext) > 0: diff -0.0157 [-0.0200, -0.0113]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2925 and no Holm-significant cell increase beyond it: diff -0.2034 [-0.2219, -0.1849]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0014 [+0.0009, +0.0019]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0014 [+0.0009, +0.0018]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0000 [-0.0000, +0.0001]

### H2_deployable: PASS
- vs `a3_global`: PASS
  - PASS utility: pooled 95% CI of (v3 - a3_global) > 0: diff +1.4332 [+1.1580, +1.7084]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.4878 and no Holm-significant cell increase beyond it: diff -2.1557 [-2.3723, -1.9391]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.1523 [-0.1827, -0.1218]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0026 [+0.0019, +0.0034]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.1366 [-0.1674, -0.1058]
- vs `cho_global`: PASS
  - PASS utility: pooled 95% CI of (v3 - cho_global) > 0: diff +0.1469 [+0.1370, +0.1567]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2862 and no Holm-significant cell increase beyond it: diff -0.1405 [-0.1835, -0.0976]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0022 [+0.0014, +0.0029]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0023 [+0.0015, +0.0030]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0004 [-0.0007, -0.0002]
- vs `cho_global_ext`: PASS
  - PASS utility: pooled 95% CI of (v3 - cho_global_ext) > 0: diff +0.1469 [+0.1370, +0.1567]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2862 and no Holm-significant cell increase beyond it: diff -0.1405 [-0.1835, -0.0976]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0022 [+0.0014, +0.0029]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0023 [+0.0015, +0.0030]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0004 [-0.0007, -0.0002]
- vs `cho_mse`: PASS
  - PASS utility: pooled 95% CI of (v3 - cho_mse) > 0: diff +0.1469 [+0.1370, +0.1567]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2862 and no Holm-significant cell increase beyond it: diff -0.1405 [-0.1835, -0.0976]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0022 [+0.0014, +0.0029]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0023 [+0.0015, +0.0030]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0004 [-0.0007, -0.0002]
- vs `cho_mro`: PASS
  - PASS utility: pooled 95% CI of (v3 - cho_mro) > 0: diff +0.1584 [+0.1376, +0.1791]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.3257 and no Holm-significant cell increase beyond it: diff -0.5348 [-0.5894, -0.4802]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0014 [-0.0023, -0.0004]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0013 [-0.0023, -0.0004]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0102 [-0.0129, -0.0076]

## Pooled over all 12 cells

| metric | v3 | a3_tuned | cho_tuned | cho_tuned_ext | a3_global | cho_global | cho_global_ext | cho_mse | cho_mro | a3_stock |
|---|---|---|---|---|---|---|---|---|---|---|
| Operator utility (objective) (per UE-min, higher better) | 11.953 [11.778, 12.128] | 11.727 [11.539, 11.914] | 11.943 [11.766, 12.121] | 11.968 [11.792, 12.145] | 10.519 [10.153, 10.885] | 11.806 [11.628, 11.983] | 11.806 [11.628, 11.983] | 11.806 [11.628, 11.983] | 11.794 [11.610, 11.978] | 8.860 [8.528, 9.192] |
| Ping-pong HOs (<1 s stay) (per UE-min, lower better) | 0.000 [-0.000, 0.000] | 0.007 [0.006, 0.008] | 0.000 [-0.000, 0.000] | 0.000 [0.000, 0.000] | 0.137 [0.106, 0.167] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.010 [0.008, 0.013] | 0.011 [0.008, 0.014] |
| Handover rate (per UE-min, lower better) | 2.722 [2.586, 2.858] | 3.647 [3.450, 3.844] | 3.073 [2.936, 3.209] | 2.925 [2.783, 3.068] | 4.878 [4.654, 5.101] | 2.862 [2.735, 2.990] | 2.862 [2.735, 2.990] | 2.862 [2.735, 2.990] | 3.257 [3.129, 3.384] | 3.336 [3.196, 3.476] |
| Failures (RLF + HO failure) (per UE-min, lower better) | 0.003 [0.002, 0.004] | 0.036 [0.031, 0.041] | 0.000 [0.000, 0.000] | 0.001 [0.001, 0.002] | 0.155 [0.124, 0.186] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.004 [0.003, 0.005] | 0.550 [0.513, 0.588] |
| Radio-link failures (per UE-min, lower better) | 0.003 [0.002, 0.003] | 0.004 [0.002, 0.005] | 0.000 [0.000, 0.000] | 0.001 [0.001, 0.002] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.004 [0.003, 0.005] | 0.000 [0.000, 0.000] |
| MRO events (late/early/wrong-cell) (per UE-min, lower better) | 0.003 [0.002, 0.004] | 0.036 [0.031, 0.041] | 0.000 [0.000, 0.000] | 0.001 [0.001, 0.002] | 0.155 [0.124, 0.186] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.004 [0.003, 0.005] | 0.550 [0.513, 0.588] |
| HO success rate (%, higher better) | 99.98 [99.97, 100.00] | 96.35 [95.54, 97.16] | 100.00 [99.99, 100.00] | 100.00 [100.00, 100.00] | 98.33 [98.08, 98.59] | 99.99 [99.98, 100.00] | 99.99 [99.98, 100.00] | 99.99 [99.98, 100.00] | 100.00 [99.99, 100.00] | 87.98 [87.32, 88.65] |
| Time in outage (%, lower better) | 0.23 [0.20, 0.26] | 0.17 [0.14, 0.20] | 0.16 [0.14, 0.19] | 0.18 [0.15, 0.21] | 0.31 [0.25, 0.37] | 0.34 [0.31, 0.37] | 0.34 [0.31, 0.37] | 0.34 [0.31, 0.37] | 0.21 [0.18, 0.23] | 1.28 [1.20, 1.37] |
| Mean throughput (Shannon proxy) (Mbps, higher better) | 154.94 [152.90, 156.99] | 157.77 [155.72, 159.81] | 155.96 [153.88, 158.03] | 155.79 [153.71, 157.87] | 157.95 [155.92, 159.98] | 153.55 [151.54, 155.56] | 153.55 [151.54, 155.56] | 153.55 [151.54, 155.56] | 155.30 [153.25, 157.35] | 153.15 [151.11, 155.19] |
| 5th-pct UE throughput (Mbps, higher better) | 110.75 [108.08, 113.43] | 113.92 [111.18, 116.67] | 111.99 [109.27, 114.70] | 111.66 [108.94, 114.39] | 114.51 [111.82, 117.19] | 109.45 [106.85, 112.05] | 109.45 [106.85, 112.05] | 109.45 [106.85, 112.05] | 111.18 [108.51, 113.86] | 108.86 [106.22, 111.49] |
| Short-stay returns (<5 s) (per UE-min, lower better) | 0.176 [0.162, 0.189] | 0.397 [0.366, 0.427] | 0.245 [0.229, 0.260] | 0.214 [0.198, 0.230] | 0.953 [0.848, 1.057] | 0.227 [0.210, 0.244] | 0.227 [0.210, 0.244] | 0.227 [0.210, 0.244] | 0.329 [0.306, 0.352] | 0.285 [0.251, 0.319] |

## v3 minus each arm (paired, pooled over 240 episodes unless fewer seeds)

| reference | utility | HO rate | failures | ping-pong | mean thr (Mbps) | cells v3 better / worse (Holm p<0.05) |
|---|---|---|---|---|---|---|
| a3_tuned | +0.226 [+0.197, +0.255] | -0.925 [-0.992, -0.858] | -0.033 [-0.038, -0.029] | -0.007 [-0.008, -0.006] | -2.822 [-2.986, -2.659] | 6 / 2 |
| cho_tuned | +0.009 [+0.003, +0.016] | -0.351 [-0.375, -0.327] | +0.002 [+0.002, +0.003] | +0.000 [-0.000, +0.000] | -1.014 [-1.083, -0.945] | 2 / 3 |
| cho_tuned_ext | -0.016 [-0.020, -0.011] | -0.203 [-0.222, -0.185] | +0.001 [+0.001, +0.002] | +0.000 [-0.000, +0.000] | -0.843 [-0.913, -0.773] | 0 / 3 |
| a3_global | +1.433 [+1.158, +1.708] | -2.156 [-2.372, -1.939] | -0.152 [-0.183, -0.122] | -0.137 [-0.167, -0.106] | -3.007 [-3.152, -2.862] | 8 / 2 |
| cho_global | +0.147 [+0.137, +0.157] | -0.141 [-0.184, -0.098] | +0.002 [+0.001, +0.003] | -0.000 [-0.001, -0.000] | +1.391 [+1.306, +1.475] | 11 / 0 |
| cho_global_ext | +0.147 [+0.137, +0.157] | -0.141 [-0.184, -0.098] | +0.002 [+0.001, +0.003] | -0.000 [-0.001, -0.000] | +1.391 [+1.306, +1.475] | 11 / 0 |
| cho_mse | +0.147 [+0.137, +0.157] | -0.141 [-0.184, -0.098] | +0.002 [+0.001, +0.003] | -0.000 [-0.001, -0.000] | +1.391 [+1.306, +1.475] | 11 / 0 |
| cho_mro | +0.158 [+0.138, +0.179] | -0.535 [-0.589, -0.480] | -0.001 [-0.002, -0.000] | -0.010 [-0.013, -0.008] | -0.356 [-0.424, -0.288] | 9 / 2 |
| a3_stock | +3.093 [+2.893, +3.292] | -0.614 [-0.709, -0.519] | -0.548 [-0.585, -0.511] | -0.011 [-0.014, -0.008] | +1.798 [+1.704, +1.893] | 11 / 0 |

### v3 - a3_tuned, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.019 [-0.002, +0.040] | 0.143 |
| rush_hour/rician | +0.305 [+0.256, +0.353] | 1.95e-17 |
| rush_hour/rayleigh | +0.997 [+0.887, +1.107] | 8.17e-25 |
| corner_turner/off | -0.047 [-0.062, -0.033] | 1.5e-07 |
| corner_turner/rician | -0.049 [-0.072, -0.027] | 0.000212 |
| corner_turner/rayleigh | +0.054 [+0.011, +0.098] | 0.0614 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.094 [+0.070, +0.117] | 6.25e-10 |
| stationary_clusters/rayleigh | +0.140 [+0.089, +0.190] | 4.1e-06 |
| cell_outage/off | +0.021 [+0.001, +0.041] | 0.131 |
| cell_outage/rician | +0.280 [+0.230, +0.329] | 2.11e-15 |
| cell_outage/rayleigh | +0.895 [+0.800, +0.991] | 2.09e-25 |

### v3 - cho_tuned, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | -0.009 [-0.023, +0.006] | 1 |
| rush_hour/rician | +0.010 [-0.006, +0.026] | 1 |
| rush_hour/rayleigh | -0.008 [-0.019, +0.002] | 0.637 |
| corner_turner/off | -0.047 [-0.062, -0.033] | 2.15e-07 |
| corner_turner/rician | -0.057 [-0.079, -0.036] | 1.54e-05 |
| corner_turner/rayleigh | -0.054 [-0.071, -0.036] | 9.33e-07 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.077 [+0.057, +0.097] | 1.53e-09 |
| stationary_clusters/rayleigh | +0.177 [+0.141, +0.213] | 5.4e-13 |
| cell_outage/off | +0.001 [-0.011, +0.013] | 1 |
| cell_outage/rician | +0.017 [+0.003, +0.032] | 0.155 |
| cell_outage/rayleigh | +0.004 [-0.005, +0.013] | 1 |

### v3 - cho_tuned_ext, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | -0.009 [-0.023, +0.006] | 1 |
| rush_hour/rician | +0.000 [-0.011, +0.012] | 1 |
| rush_hour/rayleigh | -0.008 [-0.019, +0.002] | 0.85 |
| corner_turner/off | -0.047 [-0.062, -0.033] | 2.58e-07 |
| corner_turner/rician | -0.057 [-0.079, -0.036] | 1.93e-05 |
| corner_turner/rayleigh | -0.054 [-0.071, -0.036] | 1.14e-06 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.005 [-0.002, +0.011] | 1 |
| stationary_clusters/rayleigh | -0.024 [-0.049, +0.001] | 0.56 |
| cell_outage/off | +0.001 [-0.011, +0.013] | 1 |
| cell_outage/rician | +0.000 [-0.011, +0.012] | 1 |
| cell_outage/rayleigh | +0.004 [-0.005, +0.013] | 1 |

### v3 - a3_global, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.209 [+0.168, +0.250] | 7.27e-14 |
| rush_hour/rician | +0.411 [+0.341, +0.480] | 2.57e-16 |
| rush_hour/rayleigh | +0.997 [+0.887, +1.107] | 6.69e-25 |
| corner_turner/off | -0.021 [-0.036, -0.006] | 0.0196 |
| corner_turner/rician | -0.049 [-0.072, -0.027] | 0.00017 |
| corner_turner/rayleigh | -0.021 [-0.048, +0.007] | 0.276 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +1.179 [+1.063, +1.295] | 2.55e-27 |
| stationary_clusters/rayleigh | +13.089 [+11.964, +14.213] | 2.35e-30 |
| cell_outage/off | +0.187 [+0.150, +0.224] | 7.27e-14 |
| cell_outage/rician | +0.323 [+0.267, +0.379] | 6.62e-16 |
| cell_outage/rayleigh | +0.895 [+0.800, +0.991] | 1.74e-25 |

### v3 - cho_global, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.225 [+0.212, +0.238] | 1.46e-39 |
| rush_hour/rician | +0.133 [+0.122, +0.145] | 7.69e-31 |
| rush_hour/rayleigh | +0.092 [+0.080, +0.104] | 4.29e-22 |
| corner_turner/off | +0.164 [+0.148, +0.180] | 1.34e-27 |
| corner_turner/rician | +0.094 [+0.077, +0.112] | 4.53e-15 |
| corner_turner/rayleigh | +0.065 [+0.050, +0.079] | 1.12e-11 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.076 [+0.056, +0.095] | 2.96e-10 |
| stationary_clusters/rayleigh | +0.437 [+0.380, +0.493] | 8.19e-22 |
| cell_outage/off | +0.234 [+0.219, +0.249] | 1.52e-37 |
| cell_outage/rician | +0.141 [+0.129, +0.152] | 1.02e-31 |
| cell_outage/rayleigh | +0.102 [+0.090, +0.114] | 1.51e-23 |

### v3 - cho_global_ext, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.225 [+0.212, +0.238] | 1.46e-39 |
| rush_hour/rician | +0.133 [+0.122, +0.145] | 7.69e-31 |
| rush_hour/rayleigh | +0.092 [+0.080, +0.104] | 4.29e-22 |
| corner_turner/off | +0.164 [+0.148, +0.180] | 1.34e-27 |
| corner_turner/rician | +0.094 [+0.077, +0.112] | 4.53e-15 |
| corner_turner/rayleigh | +0.065 [+0.050, +0.079] | 1.12e-11 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.076 [+0.056, +0.095] | 2.96e-10 |
| stationary_clusters/rayleigh | +0.437 [+0.380, +0.493] | 8.19e-22 |
| cell_outage/off | +0.234 [+0.219, +0.249] | 1.52e-37 |
| cell_outage/rician | +0.141 [+0.129, +0.152] | 1.02e-31 |
| cell_outage/rayleigh | +0.102 [+0.090, +0.114] | 1.51e-23 |

### v3 - cho_mse, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.225 [+0.212, +0.238] | 1.46e-39 |
| rush_hour/rician | +0.133 [+0.122, +0.145] | 7.69e-31 |
| rush_hour/rayleigh | +0.092 [+0.080, +0.104] | 4.32e-22 |
| corner_turner/off | +0.164 [+0.148, +0.180] | 1.34e-27 |
| corner_turner/rician | +0.094 [+0.077, +0.112] | 4.53e-15 |
| corner_turner/rayleigh | +0.065 [+0.050, +0.079] | 1.12e-11 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.076 [+0.056, +0.095] | 2.96e-10 |
| stationary_clusters/rayleigh | +0.437 [+0.380, +0.493] | 8.21e-22 |
| cell_outage/off | +0.234 [+0.219, +0.249] | 1.52e-37 |
| cell_outage/rician | +0.141 [+0.129, +0.152] | 1.02e-31 |
| cell_outage/rayleigh | +0.102 [+0.090, +0.114] | 1.54e-23 |

### v3 - cho_mro, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.151 [+0.123, +0.180] | 2.22e-14 |
| rush_hour/rician | +0.099 [+0.071, +0.128] | 1.26e-08 |
| rush_hour/rayleigh | +0.085 [+0.060, +0.111] | 3.58e-08 |
| corner_turner/off | +0.026 [+0.015, +0.037] | 5.21e-05 |
| corner_turner/rician | -0.034 [-0.051, -0.017] | 0.000254 |
| corner_turner/rayleigh | -0.053 [-0.067, -0.039] | 1.22e-09 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.285 [+0.259, +0.311] | 1.02e-28 |
| stationary_clusters/rayleigh | +0.969 [+0.902, +1.036] | 1.27e-35 |
| cell_outage/off | +0.158 [+0.133, +0.184] | 3.56e-17 |
| cell_outage/rician | +0.114 [+0.086, +0.142] | 3.83e-10 |
| cell_outage/rayleigh | +0.100 [+0.074, +0.125] | 9.62e-10 |

## Per cell, utility (all arms)

| cell | v3 | a3_tuned | cho_tuned | cho_tuned_ext | a3_global | cho_global | cho_global_ext | cho_mse | cho_mro | a3_stock |
|---|---|---|---|---|---|---|---|---|---|---|
| rush_hour/off | 11.002 [10.760, 11.244] | 10.983 [10.735, 11.230] | 11.010 [10.768, 11.253] | 11.010 [10.768, 11.253] | 10.793 [10.540, 11.046] | 10.777 [10.531, 11.022] | 10.777 [10.531, 11.022] | 10.777 [10.531, 11.022] | 10.851 [10.602, 11.099] | 6.386 [5.826, 6.946] |
| rush_hour/rician | 10.851 [10.606, 11.096] | 10.547 [10.288, 10.805] | 10.842 [10.597, 11.087] | 10.851 [10.606, 11.096] | 10.440 [10.174, 10.707] | 10.718 [10.471, 10.964] | 10.718 [10.471, 10.964] | 10.718 [10.471, 10.964] | 10.752 [10.505, 10.999] | 5.524 [4.959, 6.089] |
| rush_hour/rayleigh | 10.733 [10.487, 10.979] | 9.736 [9.433, 10.040] | 10.741 [10.496, 10.987] | 10.741 [10.496, 10.987] | 9.736 [9.433, 10.040] | 10.641 [10.393, 10.888] | 10.641 [10.393, 10.888] | 10.641 [10.393, 10.888] | 10.648 [10.397, 10.898] | 4.776 [4.199, 5.353] |
| corner_turner/off | 15.201 [14.740, 15.661] | 15.248 [14.785, 15.712] | 15.248 [14.785, 15.712] | 15.248 [14.785, 15.712] | 15.222 [14.757, 15.687] | 15.037 [14.575, 15.499] | 15.037 [14.575, 15.499] | 15.037 [14.575, 15.499] | 15.175 [14.712, 15.638] | 14.960 [14.503, 15.416] |
| corner_turner/rician | 15.089 [14.625, 15.552] | 15.138 [14.670, 15.606] | 15.146 [14.679, 15.613] | 15.146 [14.679, 15.613] | 15.138 [14.670, 15.606] | 14.994 [14.534, 15.455] | 14.994 [14.534, 15.455] | 14.994 [14.534, 15.455] | 15.123 [14.657, 15.588] | 14.803 [14.334, 15.272] |
| corner_turner/rayleigh | 14.996 [14.533, 15.459] | 14.942 [14.471, 15.412] | 15.049 [14.583, 15.516] | 15.049 [14.583, 15.516] | 15.017 [14.547, 15.486] | 14.931 [14.471, 15.392] | 14.931 [14.471, 15.392] | 14.931 [14.471, 15.392] | 15.049 [14.586, 15.512] | 14.458 [13.966, 14.951] |
| stationary_clusters/off | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] | 11.215 [10.680, 11.750] |
| stationary_clusters/rician | 10.976 [10.443, 11.508] | 10.882 [10.343, 11.421] | 10.899 [10.363, 11.435] | 10.971 [10.438, 11.504] | 9.797 [9.174, 10.420] | 10.900 [10.365, 11.436] | 10.900 [10.365, 11.436] | 10.900 [10.365, 11.436] | 10.691 [10.145, 11.236] | 10.454 [9.883, 11.026] |
| stationary_clusters/rayleigh | 10.623 [10.096, 11.149] | 10.483 [9.930, 11.036] | 10.446 [9.908, 10.984] | 10.646 [10.118, 11.174] | -2.466 [-4.061, -0.872] | 10.186 [9.627, 10.745] | 10.186 [9.627, 10.745] | 10.186 [9.627, 10.745] | 9.654 [9.077, 10.230] | 5.553 [4.542, 6.565] |
| cell_outage/off | 11.053 [10.745, 11.360] | 11.032 [10.722, 11.343] | 11.052 [10.744, 11.359] | 11.052 [10.744, 11.359] | 10.866 [10.549, 11.182] | 10.819 [10.509, 11.129] | 10.819 [10.509, 11.129] | 10.819 [10.509, 11.129] | 10.895 [10.581, 11.209] | 6.891 [6.295, 7.488] |
| cell_outage/rician | 10.899 [10.590, 11.208] | 10.619 [10.292, 10.947] | 10.882 [10.572, 11.191] | 10.899 [10.590, 11.208] | 10.576 [10.247, 10.904] | 10.758 [10.446, 11.070] | 10.758 [10.446, 11.070] | 10.758 [10.446, 11.070] | 10.785 [10.470, 11.100] | 6.008 [5.367, 6.649] |
| cell_outage/rayleigh | 10.793 [10.483, 11.104] | 9.898 [9.537, 10.259] | 10.789 [10.481, 11.098] | 10.789 [10.481, 11.098] | 9.898 [9.537, 10.259] | 10.691 [10.379, 11.003] | 10.691 [10.379, 11.003] | 10.691 [10.379, 11.003] | 10.694 [10.380, 11.007] | 5.287 [4.655, 5.919] |

## Arms

- `v3`: dqn2:v3.14.24
- `a3_tuned`: a3:off=-1,hys=1,ttt=0.0,k=0; a3:off=0,hys=2,ttt=0.0,k=0; a3:off=0,hys=2,ttt=0.0,k=4; a3:off=1,hys=2,ttt=0.0,k=0; a3:off=2,hys=0,ttt=0.16,k=0; a3:off=2,hys=0,ttt=0.16,k=4; a3:off=3,hys=2,ttt=0.16,k=11; a3:off=6,hys=1,ttt=1.28,k=8
- `cho_tuned`: cho:prep=-6,off=0,hys=0,ttt=0.0,k=0; cho:prep=-6,off=1,hys=1,ttt=0.0,k=0; cho:prep=-6,off=1,hys=1,ttt=0.0,k=4; cho:prep=-6,off=2,hys=0,ttt=0.16,k=4; cho:prep=-6,off=3,hys=1,ttt=0.0,k=0; cho:prep=-6,off=3,hys=1,ttt=0.0,k=4; cho:prep=-6,off=4,hys=0,ttt=0.64,k=0; cho:prep=-6,off=4,hys=1,ttt=0.0,k=4; cho:prep=-6,off=4,hys=1,ttt=0.0,k=8
- `cho_tuned_ext`: cho:prep=-6,off=-1,hys=1,ttt=0,k=0; cho:prep=-6,off=0,hys=2,ttt=0,k=0; cho:prep=-6,off=0,hys=2,ttt=0,k=4; cho:prep=-6,off=2,hys=0,ttt=0.16,k=4; cho:prep=-6,off=2,hys=2,ttt=0,k=0; cho:prep=-6,off=3,hys=2,ttt=0,k=11; cho:prep=-6,off=3,hys=2,ttt=0,k=4; cho:prep=-6,off=4,hys=2,ttt=0,k=0; cho:prep=-6,off=5,hys=0,ttt=0.16,k=0; cho:prep=-6,off=5,hys=2,ttt=0,k=8
- `a3_global`: a3:off=0,hys=2,ttt=0.0,k=4
- `cho_global`: cho:prep=-6,off=3,hys=1,ttt=0.0,k=8
- `cho_global_ext`: cho:prep=-6,off=3,hys=1,ttt=0,k=8
- `cho_mse`: mse:{"base": {"exec_offset_db": 3.0, "hys_db": 1.0, "l3_k": 8, "prep_offset_db": -6.0, "ttt_s": 0.0}, "n_high": 3, "n_med": 1, "off_high": 0.0, "off_med": 0.0, "sf_high": 0.25, "sf_med": 0.5, "stat_off_db": 0.0, "t_eval_s": 30.0}
- `cho_mro`: mro:{"base": {"exec_offset_db": 1.0, "hys_db": 2.0, "l3_k": 4, "prep_offset_db": -6.0, "ttt_s": 0.0}, "hi": 8.0, "ho_budget": 0.0, "lo": -1.0, "period_s": 10.0, "short_s": 5.0, "step_db": 0.5}
- `a3_stock`: a3
