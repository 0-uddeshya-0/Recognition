# Schedules

## Room schedule

| tag | storey | name | category | area_m2 | height_m | doors | windows |
|---|---|---|---|---|---|---|---|
| R-01 | Erdgeschoss | Küche | kitchen | 12.21 | 2.5 | D-03 | W-02 |
| R-02 | Erdgeschoss | Wohnen | living | 27.38 | 2.5 | D-01 D-02 | W-01 |
| R-03 | Erdgeschoss | Flur | hall | 18.53 | 2.5 | D-02 D-03 D-04 D-05 D-06 |  |
| R-04 | Erdgeschoss | Schlafzimmer 1 | bedroom | 15.17 | 2.5 | D-04 | W-03 |
| R-05 | Erdgeschoss | Schlafzimmer 2 | bedroom | 15.35 | 2.5 | D-05 | W-04 |
| R-06 | Erdgeschoss | Bad | bathroom | 8.51 | 2.5 | D-06 |  |

## Door schedule

| tag | storey | name | type | width_m | height_m | external | connects |
|---|---|---|---|---|---|---|---|
| D-01 | Erdgeschoss | D-00 | Eingangstuer | 0.9 | 2.1 | yes | R-02 |
| D-02 | Erdgeschoss | D-01 |  | 0.8 | 2.05 | no | R-03 / R-02 |
| D-03 | Erdgeschoss | D-02 |  | 0.8 | 2.05 | no | R-03 / R-01 |
| D-04 | Erdgeschoss | D-03 |  | 0.8 | 2.05 | no | R-03 / R-04 |
| D-05 | Erdgeschoss | D-04 |  | 0.8 | 2.05 | no | R-03 / R-05 |
| D-06 | Erdgeschoss | D-05 |  | 0.8 | 2.05 | no | R-03 / R-06 |

## Window schedule

| tag | storey | name | type | width_m | height_m | glazing_m2 | room |
|---|---|---|---|---|---|---|---|
| W-01 | Erdgeschoss | F-01 |  | 2.7 | 1.4 | 3.78 | R-02 |
| W-02 | Erdgeschoss | F-02 |  | 1.25 | 1.4 | 1.75 | R-01 |
| W-03 | Erdgeschoss | F-03 |  | 1.55 | 1.4 | 2.17 | R-04 |
| W-04 | Erdgeschoss | F-04 |  | 1.55 | 1.4 | 2.17 | R-05 |
