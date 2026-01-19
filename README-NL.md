# PowerClimate (NL)

## Audit-log

- 0.2 — Eerste publieke versie
- 0.3-beta — Verbeterde configuratie en water-warmtepomp nu optioneel
- 0.4.0-beta — Kernlogica opgesplitst, assist-regeling, zonne-energiebudgetten en opmaaktools
- 0.5-beta — Separated mirror thermostats

Home Assistant custom integration om meerdere warmtepomp `climate.*` apparaten te beheren
en hun setpoints te coordineren met per-apparaat temperatuur offsets.

Niet gelieerd aan Home Assistant.
# PowerClimate (NL)

Home Assistant custom integration om meerdere warmtepomp `climate.*` apparaten te beheren
en hun setpoints te coordineren met per-apparaat temperatuur offsets.

Niet gelieerd aan Home Assistant.

## Functies

- **Multi-warmtepomp orchestration**: een virtuele thermostaat coordineert een optionele waterwarmtepomp (0 of 1) en nul of meer lucht- (assist) warmtepompen.
- **Per-apparaat offsets + guardrails**: lower/upper offsets per apparaat, plus globale min/max setpoint limieten.
- **Assists handmatig (default) + optioneel automatisch aan/uit**: jij bepaalt of assists draaien, of laat PowerClimate assist HVAC mode beheren met timers en anti-short-cycle.
- **Vermogensbewuste regeling (optioneel)**: preset `Solar` kan per-apparaat vermogensbudgetten verdelen op basis van een signed house net power sensor.
- **Diagnostiek**: thermische samenvatting, per-HP gedrag, afgeleides, totaal vermogen en budgetdiagnostiek.
- **Thermostaat-mirroring**: kopieer setpoint-wijzigingen van geselecteerde thermostaten naar PowerClimate.
- **Werkt met standaard HA services**: stuurt bestaande `climate.*` entities via Home Assistant.

## Documentatie

- Detailed documentation (EN): [custom_components/powerclimate/README.md](custom_components/powerclimate/README.md)
- Gedetailleerde documentatie (NL): [custom_components/powerclimate/README-NL.md](custom_components/powerclimate/README-NL.md)

## Installatie

Kopieer `custom_components/powerclimate/` naar je Home Assistant `config/custom_components/` en herstart Home Assistant.

## Setup

1. Home Assistant -> **Instellingen -> Apparaten & Diensten -> Integratie toevoegen -> PowerClimate**.
2. Kies een of meerdere ruimtesensoren (PowerClimate gebruikt het gemiddelde van beschikbare waarden).
3. Selecteer thermostaten die PowerClimate moet mirroren (optioneel). Setpoint-wijzigingen daarvan worden overgenomen.
4. Selecteer een optionele waterwarmtepomp (0 of 1) en nul of meer lucht- (assist) warmtepompen. De eerste gemirrorde thermostaat wordt vooraf geselecteerd als waterwarmtepomp.

![Select heat pumps configuration](custom_components/powerclimate/images/Config_select_heat_pumps.png)

5. Configureer elk geselecteerd apparaat op een eigen pagina (rol, sensoren, offsets en optioneel aan/uit controle voor assists).

Let op: stel de lower setpoint offset zo in dat de warmtepomp net niet uit gaat. In dit voorbeeld zal setpoint op 17 graden ingesteld worden als de warmtepomp zelf 20 graden meet. 
  
![Config air warmtepomp](custom_components/powerclimate/images/Config%20air%20heatpump%201.png)

## Support

- Issues en feature requests: gebruik de GitHub issue tracker die in de integration manifest gelinkt is.

## Regel-logica

### Waterwarmtepomp (optioneel)

- Indien geconfigureerd kan PowerClimate de HVAC mode beheren: het water-apparaat wordt geforceerd naar HEAT wanneer de virtuele
  climate entity aan staat, en wordt uitgezet wanneer die uit staat.
- Het PowerClimate doelsetpoint wordt begrensd tussen lower/upper offsets (en de globale 16–30 °C limieten)
  voordat het naar het water-apparaat wordt gestuurd.
- Watertemperatuur wordt gemeten en als diagnostiek getoond (wanneer een watersensor geconfigureerd is).

### Lucht- (assist) warmtepompen (0..n)

- De gebruiker beheert de HVAC mode van elke assist. Als een assist uit staat,
  laat PowerClimate hem met rust.
- Als een assist aan staat, vergelijkt PowerClimate de ruimtetemperatuur met de gevraagde target:
  - **Minimal-modus** (kamer >= target): setpoint = huidige temp + lower offset.
  - **Setpoint-modus** (kamer < target): setpoint = target begrensd
    tussen `current + lower offset` en `current + upper offset`.
- Alle temperaturen worden begrensd tussen globale min/max voordat er commando's worden gestuurd.

## Preset Gedrag

PowerClimate presets sturen het gedrag van warmtepompen in verschillende scenario's:

| Preset | Water warmtepomp | Lucht warmtepomp(en) |
|--------|------------------|----------------------|
| **none** | Normale werking (HEAT mode, volgt setpoint) | Volgt setpoint als AAN, niet aanpassen als UIT |
| **boost** | Boost (huidig + upper offset) | Boost (huidig + upper offset) |
| **Away** | Minimal-modus (laat temp zakken naar 16 °C) | UIT (als allow_on_off aan staat), anders minimal |
| **Solar** | Vermogensgebudgetteerde setpoint (gebruik surplus) | Vermogensgebudgetteerd (prioriteit na water-HP) |

**Let op:** `Solar` vereist een geconfigureerde house net power sensor. Budgetten worden verdeeld in apparaatvolgorde, met prioriteit voor het water-apparaat wanneer aanwezig.
`Away` schakelt luchtpompen alleen uit wanneer `allow_on_off_control` voor dat apparaat is ingeschakeld.

## Configuratie-constanten

Alle controle-parameters staan in `const.py` en kunnen aangepast worden:

| Constant | Default | Beschrijving |
|----------|---------|--------------|
| `DEFAULT_MIN_SETPOINT` | 16.0 | Absoluut minimum setpoint dat ooit naar een pomp wordt gestuurd. |
| `DEFAULT_MAX_SETPOINT` | 30.0 | Absoluut maximum setpoint dat ooit naar een pomp wordt gestuurd. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_HP1` | -0.3 | HP1 minimal-modus offset t.o.v. eigen gemeten temperatuur. |
| `DEFAULT_UPPER_SETPOINT_OFFSET_HP1` | 1.5 | HP1 maximum offset t.o.v. eigen gemeten temperatuur. |
| `DEFAULT_LOWER_SETPOINT_OFFSET_ASSIST` | -4.0 | Assist minimal-modus offset (ruimte op temperatuur). |
| `DEFAULT_UPPER_SETPOINT_OFFSET_ASSIST` | 4.0 | Assist maximum offset bij het volgen van de ruimte-target. |

## Sensoren

Sensoren worden alleen aangemaakt voor pompen met een geconfigureerde `climate_entity_id`.

| Sensor | Beschrijving |
|--------|--------------|
| Temperature Derivative | Verandering van ruimtetemperatuur (°C/uur) |
| Water Derivative | Verandering van watertemperatuur (°C/uur) |
| Thermal Summary | Leesbare systeemstatus |
| HP1 Behavior | HVAC status, temps, watertemperatuur (indien beschikbaar) |
| HP2 Behavior | HVAC status, temps, en PowerClimate mode (off/minimal/setpoint/power/boost) |
| HP3 Behavior | Zelfde als hierboven wanneer een derde pomp geconfigureerd is |
| HP4 Behavior | Zelfde logica als HP2 wanneer een vierde pomp geconfigureerd is |
| HP5 Behavior | Zelfde logica als HP2 wanneer een vijfde pomp geconfigureerd is |
| Total Power | Opgeteld vermogen van alle geconfigureerde pompen |
| Power Budget | Totale + per-apparaat budgetten (wanneer actief) |

Afgeleiden gebruiken de helling tussen het oudste en nieuwste sample binnen het venster (kamer: 15 minuten, water: 10 minuten).

Behavior-sensoren labelen elke pomp als `<eerste woord> (hpX)` om te matchen met de Thermal Summary.

## Warmtepomp tips

Algemene setup tips (check altijd je handleiding):

- Assist warmtepompen (HP2-HP5): gebruik waar mogelijk "heat shift" / °C offset voor stabiele minimal-modus, en tune `lower_setpoint_offset` zodat assists netjes kunnen "idle-en".
- Water-/hybride warmtepomp (HP1): als hybride, voorkom bijschakelen van gas voor ruimteverwarming en cap de CH/flow temperatuur initieel rond 45 °C voor betere COP.

## Next Steps

- Gebruik Advanced options om assist thresholds (ETA in minuten) en anti-short-cycle te tunen
- Gebruik energiesensoren/COP data voor economische keuzes
- Voeg unit tests toe voor de assist logica
 
``` 

