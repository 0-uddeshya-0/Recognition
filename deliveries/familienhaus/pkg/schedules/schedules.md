# Schedules

## Room schedule

| tag | storey | name | category | area_m2 | height_m | doors | windows |
|---|---|---|---|---|---|---|---|
| R-01 | Erdgeschoss | Wohnen | living | 28.04 | 2.5 | D-01 D-02 | W-01 |
| R-02 | Erdgeschoss | Kinderzimmer 2 | bedroom | 11.81 | 2.5 | D-03 | W-02 |
| R-03 | Erdgeschoss | Bad | bathroom | 7.88 | 2.5 | D-04 |  |
| R-04 | Erdgeschoss | Flur | hall | 19.25 | 2.5 | D-02 D-06 D-05 D-07 D-03 D-08 D-04 |  |
| R-05 | Erdgeschoss | Elternschlafzimmer | bedroom | 14.08 | 2.5 | D-05 | W-04 |
| R-06 | Erdgeschoss | Küche | kitchen | 12.16 | 2.5 | D-06 | W-05 |
| R-07 | Erdgeschoss | Kinderzimmer 1 | bedroom | 11.68 | 2.5 | D-07 | W-06 |
| R-08 | Erdgeschoss | Büro | office | 9.92 | 2.5 | D-08 | W-03 |

## Door schedule

| tag | storey | name | type | width_m | height_m | external | connects |
|---|---|---|---|---|---|---|---|
| D-01 | Erdgeschoss | D-00 | Eingangstuer | 1.01 | 2.1 | yes | R-01 |
| D-02 | Erdgeschoss | D-01 |  | 0.885 | 2.05 | no | R-04 / R-01 |
| D-03 | Erdgeschoss | D-05 |  | 0.885 | 2.05 | no | R-04 / R-02 |
| D-04 | Erdgeschoss | D-07 |  | 0.885 | 2.05 | no | R-04 / R-03 |
| D-05 | Erdgeschoss | D-03 |  | 0.885 | 2.05 | no | R-04 / R-05 |
| D-06 | Erdgeschoss | D-02 |  | 0.885 | 2.05 | no | R-04 / R-06 |
| D-07 | Erdgeschoss | D-04 |  | 0.885 | 2.05 | no | R-04 / R-07 |
| D-08 | Erdgeschoss | D-06 |  | 0.885 | 2.05 | no | R-04 / R-08 |

## Window schedule

| tag | storey | name | type | width_m | height_m | glazing_m2 | room |
|---|---|---|---|---|---|---|---|
| W-01 | Erdgeschoss | F-01 |  | 2.75 | 1.4 | 3.85 | R-01 |
| W-02 | Erdgeschoss | F-05 |  | 1.2 | 1.4 | 1.68 | R-02 |
| W-03 | Erdgeschoss | F-06 |  | 1.0 | 1.4 | 1.4 | R-08 |
| W-04 | Erdgeschoss | F-03 |  | 1.45 | 1.4 | 2.03 | R-05 |
| W-05 | Erdgeschoss | F-02 |  | 1.2 | 1.4 | 1.68 | R-06 |
| W-06 | Erdgeschoss | F-04 |  | 1.15 | 1.4 | 1.61 | R-07 |
