# PowerClimate (NL)

Home Assistant custom integratie om meerdere warmtepomp climate devices samen te laten werken.

## Audit-log

- 0.2 — Eerste publieke versie
- 0.3-beta — Verbeterde configuratie en water-warmtepomp nu optioneel
- 0.4.0-beta — Kernlogica opgesplitst, assist-regeling, zonne-energiebudgetten en opmaaktools
- 0.5-beta — Separated mirror thermostats

## Functies

- **Combineren meerdere warmtepompen**: een virtuele thermostaat die een water-warmtepomp en lucht warmtepompen (Airco's) bestuurt.
- **Offsets + guardrails**: lower/upper offset per apparaat en globale min/max setpoints.
- **Assists: handmatig of automatisch AAN/UIT**: optionele timers + anti-short-cycle beveiliging.
- **Vermogensbewuste `Solar` preset (optioneel)**: verdeel per-apparaat vermogensbudgetten op basis van een signed house net power sensor.
- **Diagnostiek**: thermische samenvatting, per-HP behavior, afgeleides, totaal vermogen en budgetdiagnostiek.
- **Thermostaat-mirroring**: kopieer setpoint-wijzigingen van geselecteerde thermostaten naar PowerClimate.
- **Standaard HA services**: stuurt bestaande `climate.*` entities via Home Assistant.

![PowerClimate-dashboard: Home Assistant UI met de virtuele PowerClimate-thermostaat (huidige temperatuur, setpoint en modusbediening).](custom_components/powerclimate/images/Dashboard%20Climate%20device.png)

## Snelstart

1. Installeer de `powerclimate` folder onder `custom_components/`.
2. In Home Assistant: **Instellingen -> Apparaten & Diensten -> Integratie toevoegen -> PowerClimate**.
3. Kies de ruimtetemperatuursensor en selecteer optioneel thermostaten om te mirroren.
4. Configureer je warmtepompen (de eerste gemirrorde thermostaat wordt vooraf geselecteerd voor de waterwarmtepomp):
  - **Waterwarmtepomp** (optioneel): climate entity, optionele vermogenssensor, optionele water
    temperatuursensor, en offsets
  - **Lucht- (assist) warmtepompen** (optioneel, 0..n): climate entity, optionele vermogenssensor, offsets per apparaat,
    en optioneel automatische AAN/UIT controle

![Configuratievoorbeeld: selectie van warmtepompen in de PowerClimate-configuratiepagina.](custom_components/powerclimate/images/Config_select_heat_pumps.png)

## Configuratie

De configuratie is rol-gebaseerd: je kunt een optionele waterwarmtepomp
(0 of 1) configureren en nul of meer lucht- (assist) warmtepompen. Voor de
apparaatselectie kun je optioneel thermostaten kiezen waarvan setpoints worden
gemirrord naar PowerClimate. De UI toont daarna aparte configuratiepagina's per
apparaat waar je de opties kiest.

## Regel-logica

### Waterwarmtepomp (optioneel)

- Indien geconfigureerd kan PowerClimate de HVAC mode beheren: het water-apparaat wordt geforceerd naar HEAT wanneer de virtuele
  climate entity aan staat, en wordt uitgezet wanneer die uit staat.
-- Het PowerClimate doelsetpoint wordt begrensd tussen de lower/upper offsets (en de globale 16–30 °C limieten)
  voordat deze naar de warmtepompen gestuurd wordt.
- Watertemperatuur wordt gemeten en ter info wanneer een watersensor is geconfigureerd.

### Lucht warmtepompen (0..n)

#### Handmatige controle (default)

- Standaard beheert de gebruiker de HVAC mode van elke assist. Als een assist uit staat,
  laat PowerClimate hem ongemoeid.
- Als een assist aan staat, vergelijkt PowerClimate de ruimtetemperatuur met de gevraagde target:
  - **Minimal-modus** (kamer >= target): setpoint = huidige temp + lower offset.
  - **Setpoint-modus** (kamer < target): setpoint = gevraagde target begrensd
    tussen `current + lower offset` en `current + upper offset`.

#### Automatische AAN/UIT controle (optioneel)

- Zet **"Allow PowerClimate to turn device on and off"** aan voor een assist om
  PowerClimate automatisch de HVAC mode te laten beheren op basis van systeembehoefte.
- PowerClimate monitort condities en gebruikt **5-minuten timers** om snel pendelen te voorkomen:
  - **AAN-condities** (onderling exclusief met UIT-condities):
    1. **ETA > 60 minuten (default)**: ruimte doet er langer over dan de ingestelde drempel om target te bereiken
    2. **Water ≥ 40 °C**: watertemperatuur van de primaire pomp is 40 °C of hoger
    3. **Stalled onder target**: room derivative ≤ 0 EN ruimte is > 0.5 °C onder target
  - **UIT-condities** (onderling exclusief met AAN-condities):
    1. **ETA < 15 minuten (default)**: ruimte bereikt target binnen de ingestelde drempel
    2. **Stalled op target**: room derivative ≤ 0 EN ruimte zit binnen 0.5 °C van target
  - Als een conditie waar is, loopt diens timer op; de tegenovergestelde timer wordt gereset
  - Als geen AAN of UIT conditie waar is, resetten beide timers naar nul
  - Er wordt pas geschakeld als een conditie 5 minuten waar blijft (300 seconden, configureerbaar)
- **Anti-short-cycle (alleen bij assist AAN/UIT controle)**
  - Indien ingeschakeld blokkeert PowerClimate het schakelen van een assist:
    - **UIT** totdat hij minimaal *Min ON time* aan stond (default 20 minuten)
    - **AAN** totdat hij minimaal *Min OFF time* uit stond (default 10 minuten)
  - Dit geldt ook als je handmatig togglet (de integratie respecteert het protectievenster)
- Timerstatus is **alleen in-memory** en reset bij Home Assistant restart
- Alle temperaturen worden begrensd tussen globale min/max voordat er commando's worden gestuurd.

## Preset Gedrag

PowerClimate presets sturen het gedrag van warmtepompen in verschillende scenario's:

| Preset | Water warmtepomp | Lucht warmtepomp(en) |
|--------|------------------|----------------------|
| **none** | Normale werking (HEAT mode, volgt setpoint) | Volgt setpoint als AAN, niet aanpassen als UIT |
| **boost** | Boost mode (huidig + upper offset) | Boost mode (huidig + upper offset) |
| **Away** | Minimal-modus (laat temp zakken naar 16 °C) | UIT (als allow_on_off aan staat), anders minimal |
| **Solar** | Vermogensgebudgetteerde setpoint (gebruik surplus) | Vermogensgebudgetteerde setpoint (prioriteit na water-HP) |

**Let op:** Solar preset vereist een geconfigureerde house net power sensor. Budgetten worden verdeeld in apparaatvolgorde, met prioriteit voor het water-apparaat wanneer aanwezig.
Away preset schakelt luchtpompen alleen uit wanneer `allow_on_off_control` voor dat apparaat is ingeschakeld.

**Configuratie-ranges:**
- Lower setpoint offset: -5.0–0.0 °C
- Upper setpoint offset: 0.0–5.0 °C

## Geavanceerde configuratie-opties

Expert users kunnen PowerClimate tunen via **Opties -> Advanced options** in de Home Assistant UI. Deze instellingen zijn optioneel; als je ze niet invult, worden defaults gebruikt.

Te vinden via: **Instellingen -> Apparaten & Diensten -> Integraties -> PowerClimate -> Opties -> Advanced options**

| Optie | Default | Range | Beschrijving |
|--------|---------|-------|-------------|
| Min Setpoint Override | 16.0 °C | 10–25 °C | Absoluut minimum dat naar een pomp wordt gestuurd |
| Max Setpoint Override | 30.0 °C | 20–35 °C | Absoluut maximum dat naar een pomp wordt gestuurd |
| Assist Timer Duration | 300 s | 60–900 s | Seconden dat een conditie waar moet blijven voor actie |
| ON: ETA Threshold | 60 min | 5–600 min | Zet assist AAN als ETA deze duur overschrijdt |
| OFF: ETA Threshold | 15 min | 1–120 min | Zet assist UIT als ETA onder deze duur komt |
| Anti-short-cycle: Min ON time | 20 min | 0–180 min | Blokkeert UIT totdat assist minimaal zo lang AAN was |
| Anti-short-cycle: Min OFF time | 10 min | 0–180 min | Blokkeert AAN totdat assist minimaal zo lang UIT was |
| Water Temperature Threshold | 40.0 °C | 30–55 °C | Zet assist AAN wanneer water deze temperatuur bereikt |
| Stall Temperature Delta | 0.5 °C | 0.1–2 °C | Temperatuurdelta voor stall-detectie |

## Experimentele opties

Sommige features zijn bewust experimenteel en staan onder **Opties -> Experimental**.

Te vinden via: **Instellingen -> Apparaten & Diensten -> Integraties -> PowerClimate -> Opties -> Experimental**

- **House net power sensor (signed)**: kies een sensor die net active power in W rapporteert (negatief = export/surplus). Dit is vereist om de preset `Solar` te kunnen selecteren.

**Notes:**
- Wijzigingen werken direct (geen restart nodig)
- Bestaande entries zonder advanced options gebruiken defaults voor backwards compatibility
- Timers zijn in-memory en resetten bij Home Assistant restart
- Advanced options worden opgeslagen in `config_entry.options` en gemerged via `merged_entry_data()`

## Configuratie-constanten

Alle controle-parameters staan in `const.py` en kunnen aangepast worden:

| Constant | Default | Beschrijving |
|----------|---------|-------------|
| `DEFAULT_MIN_SETPOINT` | 16.0 | Absoluut minimum temperatuur die ooit naar een pomp wordt gestuurd. |
| `DEFAULT_MAX_SETPOINT` | 30.0 | Absoluut maximum temperatuur die naar een pomp wordt gestuurd. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_HP1` | -0.3 | HP1 minimal-modus offset t.o.v. eigen gemeten temperatuur. |
| `DEFAULT_UPPER_SETPOINT_OFFSET_HP1` | 1.5 | HP1 maximum offset t.o.v. eigen gemeten temperatuur. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST` | -4.0 | Assist minimal-modus offset (ruimte op temperatuur). |
| `DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST` | 4.0 | Assist maximum offset bij het volgen van de ruimte-target. |

## Sensoren

PowerClimate levert meerdere diagnostische sensors om systeemstatus te monitoren. Text sensors
gebruiken het `powerclimate_text_*` naming pattern zodat je ze makkelijk kunt excluden uit recorder.

Sensoren worden alleen aangemaakt voor pompen met een geconfigureerde `climate_entity_id`.

| Sensor | Entity ID Pattern | Beschrijving |
|--------|-------------------|-------------|
| Temperature Derivative | `sensor.powerclimate_derivative_*` | Verandering van ruimtetemperatuur (°C/uur) |
| Water Derivative | `sensor.powerclimate_water_derivative_*` | Verandering van watertemperatuur (°C/uur) |
| **Thermal Summary** | `sensor.powerclimate_text_thermal_summary_*` | Leesbare systeemstatus met alle pomptemps en ETAs |
| **Assist Summary** | `sensor.powerclimate_text_assist_summary_*` | Room state, trend, en per-pomp timer/conditie status |
| **HP1 Behavior** | `sensor.powerclimate_text_hp1_behavior_*` | HVAC status, temps, watertemperatuur wanneer beschikbaar |
| **HP2 Behavior** | `sensor.powerclimate_text_hp2_behavior_*` | HVAC status, temps, en PowerClimate mode |
| **HP3 Behavior** | `sensor.powerclimate_text_hp3_behavior_*` | Zelfde als HP2 wanneer een derde pomp geconfigureerd is |
| **HP4 Behavior** | `sensor.powerclimate_text_hp4_behavior_*` | Zelfde als HP2 wanneer een vierde pomp geconfigureerd is |
| **HP5 Behavior** | `sensor.powerclimate_text_hp5_behavior_*` | Zelfde als HP2 wanneer een vijfde pomp geconfigureerd is |
| Total Power | `sensor.powerclimate_total_power_*` | Opgeteld vermogen van geconfigureerde pompen |
| Power Budget | `sensor.powerclimate_power_budget_*` | Totaal + per-apparaat budgetten (gebruikt door `Solar` preset) |

**Text sensor details:**
- Alle text sensors (prefix `powerclimate_text_*`) kun je excluden uit recorder:
  ```yaml
  recorder:
    exclude:
      entity_globs:
        - sensor.powerclimate_text_*
  ```
- Behavior sensors labelen elke pomp als `<first word> (hpX)` om te matchen met de Thermal Summary
- Assist Summary toont:
  - Room state (temp, target, delta, trend, ETA)
  - Per-pomp status met timer countdown (bijv. "Water≥40 °C ON:3:45/5:00")
  - Conditie labels reflecteren je thresholds (bijv. ETA>60m / ETA<15m)
  - Anti-short-cycle blokkering indien van toepassing (bijv. "Blocked(min_off 420s)")
  - "Manual control" voor pompen zonder automatische AAN/UIT

## Warmtepomp tips

Algemene setup guidance (check altijd je handleiding):

- Assist pompen (HP2-HP5): gebruik waar mogelijk "heat shift" / °C offset om minimal-modus te stabiliseren; tune daarna `lower_setpoint_offset` zodat assists rustig kunnen "idle-en" wanneer de ruimte op temperatuur is.
- Water-/hybride pomp (HP1): als hybride, voorkom bijschakelen van gas voor ruimteverwarming en cap CH/flow temperatuur rond 45 °C initieel voor betere COP.

## Next Steps

- Min/max clamp values en assist timer/thresholds zijn nu configureerbaar via Advanced Options
- Gebruik energiesensoren of COP data voor economische keuzes
- Voeg unit tests toe voor assist logica en advanced configuration
- Overweeg persistent timer state (nu alleen in-memory)
