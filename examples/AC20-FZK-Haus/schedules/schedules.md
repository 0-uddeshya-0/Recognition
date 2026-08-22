# Schedules

## Room schedule

| tag | storey | name | category | area_m2 | height_m | doors | windows |
|---|---|---|---|---|---|---|---|
| R-01 | Erdgeschoss | Küche | kitchen | 16.31 | 2.5 | D-01 | W-03 W-01 |
| R-02 | Erdgeschoss | Wohnen | living | 25.99 | 2.5 | D-01 | W-02 W-04 |
| R-03 | Erdgeschoss | Flur | hall | 11.53 | 2.5 | D-03 D-05 D-04 D-02 |  |
| R-04 | Erdgeschoss | Schlafzimmer | bedroom | 22.07 | 2.5 | D-03 | W-06 W-09 |
| R-05 | Erdgeschoss | Buero | office | 12.98 | 2.5 | D-04 | W-05 W-07 |
| R-06 | Erdgeschoss | Bad | bathroom | 12.5 | 2.5 | D-05 | W-08 |
| R-07 | Dachgeschoss | Galerie | roof | 107.16 | 3.39 |  | W-10 W-11 |

## Door schedule

| tag | storey | name | type | width_m | height_m | external | connects |
|---|---|---|---|---|---|---|---|
| D-01 | Erdgeschoss | Terrassentuer | Schiebetür_3-teilig | 2.01 | 2.375 | yes | R-02 / R-01 |
| D-02 | Erdgeschoss | Haustuer | Eingangstür | 1.01 | 2.01 | yes | R-03 |
| D-03 | Erdgeschoss | Innentuer-1 | IFC Tür - Eine Öffnunsgrichtung | 0.885 | 2.01 | no | R-03 / R-04 |
| D-04 | Erdgeschoss | Innentuer-3 | IFC Tür - Eine Öffnunsgrichtung | 0.885 | 2.01 | no | R-03 / R-05 |
| D-05 | Erdgeschoss | Innentuer-2 | IFC Tür - Eine Öffnunsgrichtung | 0.885 | 2.01 | no | R-03 / R-06 |

## Window schedule

| tag | storey | name | type | width_m | height_m | glazing_m2 | room |
|---|---|---|---|---|---|---|---|
| W-01 | Erdgeschoss | EG-Fenster-4 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-01 |
| W-02 | Erdgeschoss | EG-Fenster-5 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-02 |
| W-03 | Erdgeschoss | EG-Fenster-7 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-01 |
| W-04 | Erdgeschoss | EG-Fenster-9 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-02 |
| W-05 | Erdgeschoss | EG-Fenster-6 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-05 |
| W-06 | Erdgeschoss | EG-Fenster-8 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-04 |
| W-07 | Erdgeschoss | EG-Fenster-1 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-05 |
| W-08 | Erdgeschoss | EG-Fenster-2 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-06 |
| W-09 | Erdgeschoss | EG-Fenster-3 | IFC Fenster - zwei Panele - Vertikal | 2.0 | 1.2 | 2.4 | R-04 |
| W-10 | Dachgeschoss | OG-Fenster-2 | Rundfenster 13 | 1.0 | 1.0 | 1.0 | R-07 |
| W-11 | Dachgeschoss | OG-Fenster-1 | Rundfenster 13 | 1.0 | 1.0 | 1.0 | R-07 |
