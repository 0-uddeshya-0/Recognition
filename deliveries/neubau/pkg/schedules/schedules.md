# Schedules

## Room schedule

| tag | storey | name | category | area_m2 | height_m | doors | windows |
|---|---|---|---|---|---|---|---|
| R-01 | Erdgeschoss | Bad | bathroom | 8.82 | 2.5 | D-03 D-02 |  |
| R-02 | Erdgeschoss | Büro | office | 74.37 | 2.5 | D-01 D-02 D-05 D-06 | W-01 |
| R-03 | Erdgeschoss | Küche | kitchen | 14.07 | 2.5 | D-03 D-04 | W-02 |
| R-04 | Erdgeschoss | Besprechung | meeting | 21.42 | 2.5 | D-04 |  |
| R-05 | Erdgeschoss | Flur | hall | 11.71 | 2.5 | D-05 D-07 |  |
| R-06 | Erdgeschoss | HWR | utility | 6.76 | 2.5 | D-07 |  |
| R-07 | Erdgeschoss | Stair | stair | 13.86 | 2.5 | D-06 |  |

## Door schedule

| tag | storey | name | type | width_m | height_m | external | connects |
|---|---|---|---|---|---|---|---|
| D-01 | Erdgeschoss | D-00 | Eingangstuer | 0.9 | 2.1 | yes | R-02 |
| D-02 | Erdgeschoss | D-03 |  | 0.8 | 2.05 | no | R-02 / R-01 |
| D-03 | Erdgeschoss | D-01 |  | 0.8 | 2.05 | no | R-01 / R-03 |
| D-04 | Erdgeschoss | D-02 |  | 0.8 | 2.05 | no | R-04 / R-03 |
| D-05 | Erdgeschoss | D-04 |  | 0.8 | 2.05 | no | R-02 / R-05 |
| D-06 | Erdgeschoss | D-06 |  | 0.8 | 2.05 | no | R-02 / R-07 |
| D-07 | Erdgeschoss | D-05 |  | 0.8 | 2.05 | no | R-06 / R-05 |

## Window schedule

| tag | storey | name | type | width_m | height_m | glazing_m2 | room |
|---|---|---|---|---|---|---|---|
| W-01 | Erdgeschoss | F-02 |  | 6.5 | 1.51 | 9.81 | R-02 |
| W-02 | Erdgeschoss | F-01 |  | 1.4 | 1.4 | 1.96 | R-03 |
