# PowerClimate (NL)

Home Assistant integratie om meerdere warmtepompen te besturen en hun setpoints te coordineren met offsets voor iedere warmtepomp.

## Waarom zou je deze integratie gebruiken?
Deze integratie is primair bedoeld voor situaties waarin je meer controle wil krijgen over 1 of meerdere  warmtepompen.

### Gebruik bij 1 warmtepomp
De integratie gaat er vanuit dat de eerste warmtepomp een lucht-water (of water-water) warmtepomp is die via een thermostaat wordt aangestuurd. 
- Stel je kiest setpoint 20 graden en de kamer is 17 graden. De integratie stelt de thermostaat dan in op 18,5. Zodra de ruimtetemperatuur 17,1 graden is verhoogt de integratie de thermostaat naar 18,6 net zolang tot de eind-temperatuur is bereikt. Door de geleidelijke opwarming kan voorkomen worden dat de cv-ketel wordt ingeschakeld.
- De integratie kan er ook voor zorgen dat de warmtepomp niet direct uitspringt als de ruimtetemperatuur bereikt is. 
- Bij nachtverlaging is het ongewenst als de warmtepomp uit gaat en dan 3 uur later weer aanspringt. De integratie biedt de mogelijkheid om de thermostaatuur direct op 17 graden te zetten. De warmtepomp gaat op minimaal vermogen (hoge COP!) terwijl de temperatuur langzaam daalt. De badkamer en andere kamers in het huis koelen niet onnodig af.

### Gebruik van ondersteunende lucht-lucht warmtepompen (airco's)
Bij koude buitentemperaturen, bijvoorbeeld richting het vriespunt, zal het vermogen afnemen. Om de ruimte warmte houden is een hogere watertemperatuur nodig, wat de efficientie (COP) verlaagt. Door een extra airco bij te schakelen, hoeven beide apparaten minder hard te werken en is de overall efficientie beter. Bovendien kan door deze overcapaciteit voorkomen worden dat de hybride warmtepomp de cv-ketel bijschakelt.

De powerclimate integratie maakt het mogelijk 2 of meer warmtepompen met één thermostaat te bedienen. 

## Functies
- Multi-pomp aansturing: HP1 (water) plus ondersteunende warmtepompen (HP2 t/m HP5) met eigen offsets.
- Handmatige controle: ondersteunende warmtepompen worden aangezet wanneer jij het wil. Wanneer ze aan staan past de integratie alleen hun setpoints aan.
- Offset per apparaat: onder- en bovengrenzen per warmtepomp in te stellen
- Absolute grenzen: setpoints worden standaard begrensd tussen 16°C en 30°C.
- Diagnostische sensoren: ruimte- en watertemperatuur, delta T en totaalvermogen zijn makkelijk inzichtelijk. 
- Event-gedreven reacties: zodra een gekoppelde thermostaat van status verandert worden de PowerClimate-setpoints onmiddellijk herberekend.

## Snelstart
1. Plaats `custom_components/powerclimate` in je Home Assistant-installatie.
2. Voeg de integratie toe via **Instellingen > Apparaten & Diensten > Integratie toevoegen > PowerClimate**.
3. Kies de ruimtesensor en stel offsets in voor HP1 en eventuele assist-pompen.
4. Configureer je warmtepompen:
   - HP1 (water): climate-entity, vermogenssensor, optionele watersensor, offsets.
   - Assist (HP2 t/m HP5, optioneel): climate-entity, optionele vermogenssensor, offsets.

## Regel-logica (kort)
- HP1: Aan/uit wordt door PowerClimate beheerd; setpoint wordt begrensd met offsets en absolute min/max. Watertemperatuur wordt gemonitord.
- Assists (HP2 t/m HP5): Aan/uit blijft bij de gebruiker. Als ze aan staan:
  - Minimal-modus (kamer >= doel): setpoint = huidige temp + lower offset.
  - Setpoint-modus (kamer < doel): setpoint = doel, begrensd tussen huidige temp + lower/upper offset.

## Geavanceerde opties (UI)
Voor expert users zijn er extra instellingen via **Opties → Advanced options** (Home Assistant UI).

Te vinden via: **Instellingen → Apparaten & Diensten → Integraties → PowerClimate → Opties → Advanced options**

- **Assist timer duration (s)**: hoe lang een ON/OFF conditie waar moet blijven voordat er daadwerkelijk geschakeld wordt (default 300s).
- **ETA drempels (minuten)**:
  - **ON: ETA threshold (minutes)** default 60min
  - **OFF: ETA threshold (minutes)** default 15min
- **Anti-short-cycle (alleen als `allow_on_off_control` aan staat voor een assist-pomp)**:
  - **Minimum ON time** default 20min (blokkeert vroegtijdig uitschakelen)
  - **Minimum OFF time** default 10min (blokkeert te snel weer inschakelen)

Let op: timers zijn in-memory en resetten bij een Home Assistant restart.

## Sensoren (config-gedreven)
Sensoren worden alleen aangemaakt voor pompen met een geconfigureerde `climate_entity_id`.

- Temperatuurafgeleide (kamer, °C/uur)
- Waterafgeleide (°C/uur)
- Thermische samenvatting (labels als `EersteWoord (hpX)`)
- HP1 Behavior (inclusief watertemperatuur, indien beschikbaar)
- HP2 Behavior (als geconfigureerd)
- HP3 Behavior (als geconfigureerd)
- HP4 Behavior (als geconfigureerd)
- HP5 Behavior (als geconfigureerd)
- Totaal vermogen (som van geconfigureerde vermogenssensoren)

Voorbeeld van de Thermische samenvatting en behavior sensoren

**Thermal summary:** Room 19.0°C→19.5°C | ΔT 0.4°C/h | ETA 1.3h | Power 1567 W

**HP1 Behavior:** Diyless (hp1) active | HVAC HEAT | Temps 18.9°C→19.5°C | ΔT 0.0°C/h | ETA none | Water 36.0°C | Water ΔT 10.8°C/h | Power 1243 W

**HP 2 Behavior:** Senhus (hp2) idle | HVAC OFF | Temps 19.0°C→18.0°C | ΔT 0.0°C/h | ETA none | Power 1 W | Assist off

**HP 3 Behavior:**
Living (hp3) active | HVAC HEAT | Temps 18.0°C→19.5°C | ΔT 0.0°C/h | ETA none | Power 324 W | Assist setpoint

## Tips voor warmtepompen
Algemene best practices (samengevat uit gangbare community-adviezen; controleer altijd de handleiding van je toestel):

- Assist-pompen (HP2 t/m HP5): gebruik waar mogelijk de "heat shift" of °C-offsetfunctie van de fabrikant om een stabiele minimal-modus te krijgen; stem de `lower_setpoint_offset` hierop af zodat de assist netjes in minimale stand blijft wanneer de ruimte op temperatuur is.
- Water-/hybride warmtepompen (HP1): als het een hybride toestel is, voorkom inschakelen van de CV-ketel door de cv-aanvoertemperatuur (CH max) in te stellen op ~45°C 

## Volgende stappen
- Anti-short-cycle en ETA-drempels finetunen via Advanced options.
- Energie- of COP-data gebruiken voor economische keuzes.
- Unit tests uitbreiden voor gedragssensoren en assist-logica.
