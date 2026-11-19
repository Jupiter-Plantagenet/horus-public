# HORUS v3 evaluation — twin v2, opencellid map, seeds 2300..2359 (n=60 per cell, PRE-REGISTERED HELD-OUT)

Generated 2026-11-18T13:21:47Z at commit d1bd28d. All arms on identical radio traces per (cell, seed), run in one sim pass per trace. Means with 95% t-CIs over episodes.

## Pre-registered go/no-go (finals_preregistration_v3.json): **NO-GO**

### H1_oracle: FAIL
- vs `a3_tuned`: PASS
  - PASS utility: pooled 95% CI of (v3 - a3_tuned) > 0: diff +0.2655 [+0.2343, +0.2967]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.3538 and no Holm-significant cell increase beyond it: diff -0.7020 [-0.7625, -0.6414]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0363 [-0.0414, -0.0312]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0018 [-0.0028, -0.0008]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0072 [-0.0083, -0.0062]
- vs `cho_tuned`: FAIL
  - PASS utility: pooled 95% CI of (v3 - cho_tuned) > 0: diff +0.0269 [+0.0210, +0.0328]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2973 and no Holm-significant cell increase beyond it: diff -0.1371 [-0.1615, -0.1128]
  - FAIL guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0033 [+0.0023, +0.0044]; regressed cells ['stationary_clusters/rayleigh']
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0033 [+0.0023, +0.0043]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0003 [-0.0000, +0.0005]
- vs `cho_tuned_ext`: FAIL
  - FAIL utility: pooled 95% CI of (v3 - cho_tuned_ext) > 0: diff +0.0033 [-0.0014, +0.0080]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.2825 and no Holm-significant cell increase beyond it: diff +0.0109 [-0.0026, +0.0243]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0019 [+0.0013, +0.0025]
  - PASS guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0019 [+0.0012, +0.0025]
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0003 [+0.0000, +0.0006]

### H2_deployable: FAIL
- vs `a3_global`: FAIL
  - PASS utility: pooled 95% CI of (v3 - a3_global) > 0: diff +1.5958 [+1.2977, +1.8938]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.4804 and no Holm-significant cell increase beyond it: diff -1.9676 [-2.1925, -1.7427]
  - PASS guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.1751 [-0.2095, -0.1408]
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0037 [+0.0026, +0.0048]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.1412 [-0.1730, -0.1093]
- vs `cho_global`: FAIL
  - PASS utility: pooled 95% CI of (v3 - cho_global) > 0: diff +0.1652 [+0.1558, +0.1746]
  - FAIL guardrail ho_rate: pooled upper CI of increase <= 0.2771 and no Holm-significant cell increase beyond it: diff +0.0650 [+0.0172, +0.1128]; regressed cells ['rush_hour/off', 'rush_hour/rician', 'corner_turner/off', 'corner_turner/rician', 'corner_turner/rayleigh', 'cell_outage/off', 'cell_outage/rician']
  - FAIL guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0030 [+0.0019, +0.0041]; regressed cells ['stationary_clusters/rayleigh']
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0031 [+0.0021, +0.0042]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0000 [-0.0004, +0.0003]
- vs `cho_global_ext`: FAIL
  - PASS utility: pooled 95% CI of (v3 - cho_global_ext) > 0: diff +0.1652 [+0.1558, +0.1746]
  - FAIL guardrail ho_rate: pooled upper CI of increase <= 0.2771 and no Holm-significant cell increase beyond it: diff +0.0650 [+0.0172, +0.1128]; regressed cells ['rush_hour/off', 'rush_hour/rician', 'corner_turner/off', 'corner_turner/rician', 'corner_turner/rayleigh', 'cell_outage/off', 'cell_outage/rician']
  - FAIL guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0030 [+0.0019, +0.0041]; regressed cells ['stationary_clusters/rayleigh']
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0031 [+0.0021, +0.0042]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0000 [-0.0004, +0.0003]
- vs `cho_mse`: FAIL
  - PASS utility: pooled 95% CI of (v3 - cho_mse) > 0: diff +0.1652 [+0.1558, +0.1746]
  - FAIL guardrail ho_rate: pooled upper CI of increase <= 0.2771 and no Holm-significant cell increase beyond it: diff +0.0649 [+0.0172, +0.1127]; regressed cells ['rush_hour/off', 'rush_hour/rician', 'corner_turner/off', 'corner_turner/rician', 'corner_turner/rayleigh', 'cell_outage/off', 'cell_outage/rician']
  - FAIL guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0030 [+0.0019, +0.0041]; regressed cells ['stationary_clusters/rayleigh']
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff +0.0031 [+0.0021, +0.0042]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0000 [-0.0004, +0.0003]
- vs `cho_mro`: FAIL
  - PASS utility: pooled 95% CI of (v3 - cho_mro) > 0: diff +0.1748 [+0.1555, +0.1941]
  - PASS guardrail ho_rate: pooled upper CI of increase <= 0.3182 and no Holm-significant cell increase beyond it: diff -0.3465 [-0.4075, -0.2855]
  - FAIL guardrail fail_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0003 [-0.0015, +0.0009]; regressed cells ['stationary_clusters/rayleigh']
  - FAIL guardrail rlf_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0003 [-0.0015, +0.0010]; regressed cells ['stationary_clusters/rayleigh']
  - PASS guardrail pp_rate: pooled upper CI of increase <= 0.0200 and no Holm-significant cell increase beyond it: diff -0.0089 [-0.0113, -0.0066]

## Pooled over all 12 cells

| metric | v3 | a3_tuned | cho_tuned | cho_tuned_ext | a3_global | cho_global | cho_global_ext | cho_mse | cho_mro | a3_stock |
|---|---|---|---|---|---|---|---|---|---|---|
| Operator utility (objective) (per UE-min, higher better) | 12.138 [11.957, 12.320] | 11.873 [11.678, 12.068] | 12.111 [11.928, 12.294] | 12.135 [11.953, 12.317] | 10.543 [10.154, 10.931] | 11.973 [11.791, 12.156] | 11.973 [11.791, 12.156] | 11.973 [11.791, 12.156] | 11.963 [11.775, 12.152] | 9.011 [8.667, 9.356] |
| Ping-pong HOs (<1 s stay) (per UE-min, lower better) | 0.000 [0.000, 0.001] | 0.008 [0.007, 0.009] | 0.000 [-0.000, 0.000] | 0.000 [-0.000, 0.000] | 0.142 [0.110, 0.173] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.009 [0.007, 0.012] | 0.010 [0.007, 0.013] |
| Handover rate (per UE-min, lower better) | 2.836 [2.695, 2.977] | 3.538 [3.345, 3.731] | 2.973 [2.839, 3.107] | 2.825 [2.685, 2.965] | 4.804 [4.578, 5.029] | 2.771 [2.647, 2.895] | 2.771 [2.647, 2.895] | 2.771 [2.647, 2.895] | 3.182 [3.056, 3.309] | 3.256 [3.118, 3.394] |
| Failures (RLF + HO failure) (per UE-min, lower better) | 0.004 [0.003, 0.005] | 0.040 [0.035, 0.045] | 0.000 [0.000, 0.001] | 0.002 [0.001, 0.003] | 0.179 [0.144, 0.214] | 0.001 [0.001, 0.001] | 0.001 [0.001, 0.001] | 0.001 [0.001, 0.001] | 0.004 [0.003, 0.005] | 0.553 [0.515, 0.591] |
| Radio-link failures (per UE-min, lower better) | 0.004 [0.003, 0.005] | 0.005 [0.004, 0.007] | 0.000 [0.000, 0.001] | 0.002 [0.001, 0.002] | 0.000 [0.000, 0.000] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.004 [0.003, 0.005] | 0.000 [0.000, 0.000] |
| MRO events (late/early/wrong-cell) (per UE-min, lower better) | 0.004 [0.003, 0.005] | 0.040 [0.035, 0.045] | 0.000 [0.000, 0.001] | 0.002 [0.001, 0.003] | 0.179 [0.144, 0.214] | 0.001 [0.001, 0.001] | 0.001 [0.001, 0.001] | 0.001 [0.001, 0.001] | 0.004 [0.003, 0.005] | 0.553 [0.515, 0.591] |
| HO success rate (%, higher better) | 99.98 [99.97, 100.00] | 96.44 [95.67, 97.20] | 100.00 [100.00, 100.00] | 99.99 [99.97, 100.00] | 98.11 [97.83, 98.39] | 99.99 [99.99, 100.00] | 99.99 [99.99, 100.00] | 99.99 [99.99, 100.00] | 100.00 [99.99, 100.00] | 87.71 [87.02, 88.41] |
| Time in outage (%, lower better) | 0.22 [0.19, 0.25] | 0.19 [0.16, 0.22] | 0.17 [0.15, 0.20] | 0.19 [0.16, 0.22] | 0.36 [0.29, 0.43] | 0.35 [0.32, 0.38] | 0.35 [0.32, 0.38] | 0.35 [0.32, 0.38] | 0.21 [0.19, 0.23] | 1.30 [1.21, 1.39] |
| Mean throughput (Shannon proxy) (Mbps, higher better) | 157.68 [155.58, 159.79] | 159.39 [157.31, 161.48] | 157.65 [155.53, 159.76] | 157.48 [155.36, 159.61] | 159.53 [157.46, 161.61] | 155.27 [153.21, 157.32] | 155.27 [153.21, 157.32] | 155.27 [153.21, 157.32] | 157.06 [154.96, 159.16] | 154.83 [152.74, 156.92] |
| 5th-pct UE throughput (Mbps, higher better) | 113.21 [110.27, 116.14] | 115.01 [112.05, 117.97] | 113.08 [110.14, 116.02] | 112.77 [109.81, 115.72] | 115.55 [112.65, 118.46] | 110.52 [107.71, 113.33] | 110.52 [107.71, 113.33] | 110.52 [107.71, 113.33] | 112.53 [109.63, 115.42] | 109.94 [107.08, 112.80] |
| Short-stay returns (<5 s) (per UE-min, lower better) | 0.202 [0.187, 0.216] | 0.385 [0.355, 0.414] | 0.237 [0.222, 0.252] | 0.205 [0.190, 0.220] | 0.929 [0.829, 1.030] | 0.213 [0.197, 0.229] | 0.213 [0.197, 0.229] | 0.213 [0.197, 0.229] | 0.323 [0.300, 0.345] | 0.269 [0.237, 0.301] |

## v3 minus each arm (paired, pooled over 240 episodes unless fewer seeds)

| reference | utility | HO rate | failures | ping-pong | mean thr (Mbps) | cells v3 better / worse (Holm p<0.05) |
|---|---|---|---|---|---|---|
| a3_tuned | +0.266 [+0.234, +0.297] | -0.702 [-0.763, -0.641] | -0.036 [-0.041, -0.031] | -0.007 [-0.008, -0.006] | -1.709 [-1.840, -1.578] | 9 / 1 |
| cho_tuned | +0.027 [+0.021, +0.033] | -0.137 [-0.161, -0.113] | +0.003 [+0.002, +0.004] | +0.000 [-0.000, +0.001] | +0.036 [-0.012, +0.084] | 7 / 0 |
| cho_tuned_ext | +0.003 [-0.001, +0.008] | +0.011 [-0.003, +0.024] | +0.002 [+0.001, +0.003] | +0.000 [+0.000, +0.001] | +0.201 [+0.150, +0.252] | 3 / 1 |
| a3_global | +1.596 [+1.298, +1.894] | -1.968 [-2.193, -1.743] | -0.175 [-0.209, -0.141] | -0.141 [-0.173, -0.109] | -1.849 [-1.967, -1.731] | 9 / 0 |
| cho_global | +0.165 [+0.156, +0.175] | +0.065 [+0.017, +0.113] | +0.003 [+0.002, +0.004] | -0.000 [-0.000, +0.000] | +2.419 [+2.287, +2.550] | 11 / 0 |
| cho_global_ext | +0.165 [+0.156, +0.175] | +0.065 [+0.017, +0.113] | +0.003 [+0.002, +0.004] | -0.000 [-0.000, +0.000] | +2.419 [+2.287, +2.550] | 11 / 0 |
| cho_mse | +0.165 [+0.156, +0.175] | +0.065 [+0.017, +0.113] | +0.003 [+0.002, +0.004] | -0.000 [-0.000, +0.000] | +2.418 [+2.287, +2.550] | 11 / 0 |
| cho_mro | +0.175 [+0.156, +0.194] | -0.346 [-0.407, -0.285] | -0.000 [-0.002, +0.001] | -0.009 [-0.011, -0.007] | +0.623 [+0.546, +0.700] | 10 / 0 |
| a3_stock | +3.127 [+2.921, +3.333] | -0.420 [-0.520, -0.320] | -0.549 [-0.587, -0.511] | -0.010 [-0.012, -0.007] | +2.858 [+2.724, +2.992] | 11 / 0 |

### v3 - a3_tuned, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.041 [+0.025, +0.057] | 1.98e-05 |
| rush_hour/rician | +0.345 [+0.308, +0.382] | 3.14e-25 |
| rush_hour/rayleigh | +1.091 [+0.975, +1.208] | 2.26e-25 |
| corner_turner/off | -0.005 [-0.010, -0.001] | 0.0399 |
| corner_turner/rician | -0.016 [-0.030, -0.002] | 0.0566 |
| corner_turner/rayleigh | +0.065 [+0.028, +0.102] | 0.00331 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.105 [+0.078, +0.132] | 1.25e-09 |
| stationary_clusters/rayleigh | +0.158 [+0.112, +0.204] | 3.29e-08 |
| cell_outage/off | +0.041 [+0.025, +0.057] | 1.98e-05 |
| cell_outage/rician | +0.331 [+0.295, +0.367] | 4.23e-25 |
| cell_outage/rayleigh | +1.031 [+0.920, +1.143] | 3.04e-25 |

### v3 - cho_tuned, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.021 [+0.007, +0.035] | 0.0248 |
| rush_hour/rician | +0.038 [+0.023, +0.052] | 1.81e-05 |
| rush_hour/rayleigh | +0.017 [+0.003, +0.030] | 0.0664 |
| corner_turner/off | -0.005 [-0.010, -0.001] | 0.0664 |
| corner_turner/rician | -0.016 [-0.030, -0.002] | 0.0849 |
| corner_turner/rayleigh | -0.003 [-0.018, +0.012] | 1 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.062 [+0.044, +0.081] | 9.55e-08 |
| stationary_clusters/rayleigh | +0.131 [+0.084, +0.178] | 5.96e-06 |
| cell_outage/off | +0.024 [+0.009, +0.039] | 0.0152 |
| cell_outage/rician | +0.036 [+0.021, +0.051] | 0.000142 |
| cell_outage/rayleigh | +0.019 [+0.005, +0.032] | 0.0436 |

### v3 - cho_tuned_ext, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.021 [+0.007, +0.035] | 0.0319 |
| rush_hour/rician | +0.030 [+0.017, +0.043] | 0.000241 |
| rush_hour/rayleigh | +0.017 [+0.003, +0.030] | 0.093 |
| corner_turner/off | -0.005 [-0.010, -0.001] | 0.093 |
| corner_turner/rician | -0.016 [-0.030, -0.002] | 0.113 |
| corner_turner/rayleigh | -0.003 [-0.018, +0.012] | 1 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | -0.000 [-0.006, +0.005] | 1 |
| stationary_clusters/rayleigh | -0.064 [-0.099, -0.029] | 0.00568 |
| cell_outage/off | +0.024 [+0.009, +0.039] | 0.019 |
| cell_outage/rician | +0.017 [+0.003, +0.032] | 0.107 |
| cell_outage/rayleigh | +0.019 [+0.005, +0.032] | 0.0581 |

### v3 - a3_global, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.249 [+0.206, +0.292] | 4.07e-16 |
| rush_hour/rician | +0.501 [+0.432, +0.570] | 2.75e-20 |
| rush_hour/rayleigh | +1.091 [+0.975, +1.208] | 1.88e-25 |
| corner_turner/off | +0.021 [+0.016, +0.026] | 3.83e-10 |
| corner_turner/rician | -0.016 [-0.030, -0.002] | 0.0849 |
| corner_turner/rayleigh | +0.030 [+0.002, +0.058] | 0.0849 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +1.239 [+1.127, +1.350] | 2.42e-29 |
| stationary_clusters/rayleigh | +14.346 [+13.226, +15.465] | 1.34e-32 |
| cell_outage/off | +0.229 [+0.190, +0.268] | 4.07e-16 |
| cell_outage/rician | +0.429 [+0.358, +0.499] | 6.4e-17 |
| cell_outage/rayleigh | +1.031 [+0.920, +1.143] | 2.49e-25 |

### v3 - cho_global, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.244 [+0.229, +0.258] | 5.8e-39 |
| rush_hour/rician | +0.155 [+0.139, +0.171] | 2.51e-26 |
| rush_hour/rayleigh | +0.105 [+0.091, +0.119] | 9.8e-21 |
| corner_turner/off | +0.234 [+0.214, +0.254] | 1.28e-30 |
| corner_turner/rician | +0.169 [+0.150, +0.189] | 1.57e-23 |
| corner_turner/rayleigh | +0.130 [+0.109, +0.151] | 1.06e-17 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.058 [+0.040, +0.077] | 5.4e-08 |
| stationary_clusters/rayleigh | +0.376 [+0.322, +0.430] | 9.32e-20 |
| cell_outage/off | +0.248 [+0.228, +0.268] | 2.04e-31 |
| cell_outage/rician | +0.151 [+0.132, +0.169] | 2.43e-22 |
| cell_outage/rayleigh | +0.113 [+0.098, +0.127] | 3.38e-21 |

### v3 - cho_global_ext, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.244 [+0.229, +0.258] | 5.8e-39 |
| rush_hour/rician | +0.155 [+0.139, +0.171] | 2.51e-26 |
| rush_hour/rayleigh | +0.105 [+0.091, +0.119] | 9.8e-21 |
| corner_turner/off | +0.234 [+0.214, +0.254] | 1.28e-30 |
| corner_turner/rician | +0.169 [+0.150, +0.189] | 1.57e-23 |
| corner_turner/rayleigh | +0.130 [+0.109, +0.151] | 1.06e-17 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.058 [+0.040, +0.077] | 5.4e-08 |
| stationary_clusters/rayleigh | +0.376 [+0.322, +0.430] | 9.32e-20 |
| cell_outage/off | +0.248 [+0.228, +0.268] | 2.04e-31 |
| cell_outage/rician | +0.151 [+0.132, +0.169] | 2.43e-22 |
| cell_outage/rayleigh | +0.113 [+0.098, +0.127] | 3.38e-21 |

### v3 - cho_mse, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.244 [+0.229, +0.258] | 5.8e-39 |
| rush_hour/rician | +0.155 [+0.139, +0.171] | 2.51e-26 |
| rush_hour/rayleigh | +0.105 [+0.091, +0.119] | 1e-20 |
| corner_turner/off | +0.234 [+0.214, +0.254] | 1.28e-30 |
| corner_turner/rician | +0.169 [+0.150, +0.189] | 1.57e-23 |
| corner_turner/rayleigh | +0.130 [+0.109, +0.151] | 1.06e-17 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.058 [+0.040, +0.077] | 5.4e-08 |
| stationary_clusters/rayleigh | +0.376 [+0.322, +0.430] | 9.25e-20 |
| cell_outage/off | +0.248 [+0.228, +0.268] | 2.04e-31 |
| cell_outage/rician | +0.151 [+0.132, +0.169] | 2.42e-22 |
| cell_outage/rayleigh | +0.113 [+0.098, +0.127] | 3.53e-21 |

### v3 - cho_mro, utility per cell

| cell | diff [95% CI] | p_holm |
|---|---|---|
| rush_hour/off | +0.177 [+0.152, +0.202] | 1.19e-19 |
| rush_hour/rician | +0.120 [+0.094, +0.146] | 3.57e-12 |
| rush_hour/rayleigh | +0.095 [+0.069, +0.121] | 2.64e-09 |
| corner_turner/off | +0.073 [+0.061, +0.086] | 3.18e-16 |
| corner_turner/rician | +0.019 [+0.005, +0.033] | 0.0218 |
| corner_turner/rayleigh | -0.010 [-0.020, +0.000] | 0.121 |
| stationary_clusters/off | +0.000 [+0.000, +0.000] | 1 |
| stationary_clusters/rician | +0.281 [+0.252, +0.310] | 2.07e-26 |
| stationary_clusters/rayleigh | +0.927 [+0.861, +0.993] | 8.09e-35 |
| cell_outage/off | +0.178 [+0.151, +0.204] | 7.37e-19 |
| cell_outage/rician | +0.125 [+0.098, +0.152] | 1.9e-12 |
| cell_outage/rayleigh | +0.112 [+0.091, +0.133] | 1.55e-14 |

## Per cell, utility (all arms)

| cell | v3 | a3_tuned | cho_tuned | cho_tuned_ext | a3_global | cho_global | cho_global_ext | cho_mse | cho_mro | a3_stock |
|---|---|---|---|---|---|---|---|---|---|---|
| rush_hour/off | 11.222 [10.951, 11.493] | 11.181 [10.904, 11.458] | 11.201 [10.927, 11.475] | 11.201 [10.927, 11.475] | 10.973 [10.691, 11.255] | 10.978 [10.703, 11.254] | 10.978 [10.703, 11.254] | 10.978 [10.703, 11.254] | 11.045 [10.772, 11.317] | 6.757 [6.189, 7.325] |
| rush_hour/rician | 11.071 [10.801, 11.342] | 10.726 [10.441, 11.012] | 11.034 [10.757, 11.310] | 11.041 [10.769, 11.314] | 10.571 [10.271, 10.870] | 10.917 [10.642, 11.191] | 10.917 [10.642, 11.191] | 10.917 [10.642, 11.191] | 10.951 [10.678, 11.225] | 5.921 [5.322, 6.521] |
| rush_hour/rayleigh | 10.955 [10.682, 11.227] | 9.863 [9.534, 10.192] | 10.938 [10.664, 11.212] | 10.938 [10.664, 11.212] | 9.863 [9.534, 10.192] | 10.850 [10.576, 11.123] | 10.850 [10.576, 11.123] | 10.849 [10.576, 11.123] | 10.859 [10.586, 11.132] | 5.089 [4.494, 5.684] |
| corner_turner/off | 15.399 [14.909, 15.889] | 15.404 [14.914, 15.894] | 15.404 [14.914, 15.894] | 15.404 [14.914, 15.894] | 15.378 [14.888, 15.868] | 15.165 [14.672, 15.658] | 15.165 [14.672, 15.658] | 15.165 [14.672, 15.658] | 15.325 [14.834, 15.817] | 15.098 [14.599, 15.598] |
| corner_turner/rician | 15.300 [14.811, 15.788] | 15.316 [14.827, 15.805] | 15.316 [14.827, 15.805] | 15.316 [14.827, 15.805] | 15.316 [14.827, 15.805] | 15.130 [14.638, 15.623] | 15.130 [14.638, 15.623] | 15.130 [14.638, 15.623] | 15.281 [14.789, 15.773] | 14.969 [14.464, 15.474] |
| corner_turner/rayleigh | 15.205 [14.719, 15.692] | 15.140 [14.654, 15.626] | 15.208 [14.721, 15.695] | 15.208 [14.721, 15.695] | 15.175 [14.685, 15.665] | 15.075 [14.583, 15.568] | 15.075 [14.583, 15.568] | 15.075 [14.583, 15.568] | 15.215 [14.727, 15.703] | 14.697 [14.177, 15.217] |
| stationary_clusters/off | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] | 11.517 [10.984, 12.050] |
| stationary_clusters/rician | 11.262 [10.735, 11.790] | 11.158 [10.624, 11.692] | 11.200 [10.670, 11.731] | 11.263 [10.735, 11.791] | 10.024 [9.417, 10.630] | 11.204 [10.673, 11.735] | 11.204 [10.673, 11.735] | 11.204 [10.673, 11.735] | 10.981 [10.441, 11.522] | 10.730 [10.168, 11.292] |
| stationary_clusters/rayleigh | 10.827 [10.284, 11.371] | 10.670 [10.108, 11.232] | 10.696 [10.161, 11.232] | 10.891 [10.360, 11.423] | -3.518 [-5.097, -1.939] | 10.451 [9.901, 11.001] | 10.451 [9.901, 11.001] | 10.451 [9.901, 11.001] | 9.900 [9.334, 10.467] | 5.400 [4.425, 6.375] |
| cell_outage/off | 11.106 [10.709, 11.504] | 11.065 [10.664, 11.467] | 11.082 [10.682, 11.482] | 11.082 [10.682, 11.482] | 10.877 [10.471, 11.284] | 10.858 [10.451, 11.266] | 10.858 [10.451, 11.266] | 10.858 [10.451, 11.266] | 10.929 [10.528, 11.330] | 6.856 [6.069, 7.643] |
| cell_outage/rician | 10.950 [10.549, 11.351] | 10.620 [10.204, 11.036] | 10.914 [10.510, 11.319] | 10.933 [10.530, 11.336] | 10.522 [10.085, 10.958] | 10.800 [10.393, 11.207] | 10.800 [10.393, 11.207] | 10.800 [10.393, 11.207] | 10.826 [10.427, 11.224] | 5.952 [5.107, 6.797] |
| cell_outage/rayleigh | 10.844 [10.443, 11.245] | 9.813 [9.350, 10.275] | 10.825 [10.422, 11.229] | 10.825 [10.422, 11.229] | 9.813 [9.350, 10.275] | 10.731 [10.325, 11.137] | 10.731 [10.325, 11.137] | 10.731 [10.325, 11.137] | 10.732 [10.330, 11.134] | 5.147 [4.309, 5.985] |

## Arms

- `v3`: dqn2:v3.14.32
- `a3_tuned`: a3:off=-1,hys=1,ttt=0.0,k=0; a3:off=0,hys=2,ttt=0.0,k=0; a3:off=0,hys=2,ttt=0.0,k=4; a3:off=1,hys=2,ttt=0.0,k=0; a3:off=2,hys=0,ttt=0.16,k=0; a3:off=2,hys=0,ttt=0.16,k=4; a3:off=3,hys=2,ttt=0.16,k=11; a3:off=6,hys=1,ttt=1.28,k=8
- `cho_tuned`: cho:prep=-6,off=0,hys=0,ttt=0.0,k=0; cho:prep=-6,off=1,hys=1,ttt=0.0,k=0; cho:prep=-6,off=1,hys=1,ttt=0.0,k=4; cho:prep=-6,off=2,hys=0,ttt=0.16,k=4; cho:prep=-6,off=3,hys=1,ttt=0.0,k=0; cho:prep=-6,off=3,hys=1,ttt=0.0,k=4; cho:prep=-6,off=4,hys=0,ttt=0.64,k=0; cho:prep=-6,off=4,hys=1,ttt=0.0,k=4; cho:prep=-6,off=4,hys=1,ttt=0.0,k=8
- `cho_tuned_ext`: cho:prep=-6,off=-1,hys=1,ttt=0,k=0; cho:prep=-6,off=0,hys=2,ttt=0,k=0; cho:prep=-6,off=0,hys=2,ttt=0,k=4; cho:prep=-6,off=2,hys=0,ttt=0.16,k=4; cho:prep=-6,off=2,hys=2,ttt=0,k=0; cho:prep=-6,off=3,hys=2,ttt=0,k=11; cho:prep=-6,off=3,hys=2,ttt=0,k=4; cho:prep=-6,off=4,hys=2,ttt=0,k=0; cho:prep=-6,off=5,hys=0,ttt=0.16,k=0; cho:prep=-6,off=5,hys=2,ttt=0,k=8
- `a3_global`: a3:off=0,hys=2,ttt=0.0,k=4
- `cho_global`: cho:prep=-6,off=3,hys=1,ttt=0.0,k=8
- `cho_global_ext`: cho:prep=-6,off=3,hys=1,ttt=0,k=8
- `cho_mse`: mse:{"base": {"exec_offset_db": 3.0, "hys_db": 1.0, "l3_k": 8, "prep_offset_db": -6.0, "ttt_s": 0.0}, "n_high": 3, "n_med": 1, "off_high": 0.0, "off_med": 0.0, "sf_high": 0.25, "sf_med": 0.5, "stat_off_db": 0.0, "t_eval_s": 30.0}
- `cho_mro`: mro:{"base": {"exec_offset_db": 1.0, "hys_db": 2.0, "l3_k": 4, "prep_offset_db": -6.0, "ttt_s": 0.0}, "hi": 8.0, "ho_budget": 0.0, "lo": -1.0, "period_s": 10.0, "short_s": 5.0, "step_db": 0.5}
- `a3_stock`: a3
