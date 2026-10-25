# PowerClimate (NL)

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue?logo=hacs)](https://github.com/hacs/integration)

Home Assistant custom integratie waarmee één virtuele thermostaat meerdere
warmtepompen samen laat werken: een optionele waterwarmtepomp plus een
willekeurig aantal lucht- (assist) warmtepompen. PowerClimate stemt hun
setpoints af met temperatuur-offsets per apparaat en kan assists zelf aan- en
uitzetten.

Niet gelieerd aan Home Assistant.

![PowerClimate op de integratiepagina van Home Assistant, met een hub per geconfigureerde ruimte of installatie.](docs/images/integration-page.png)

## Functies

- **Meerdere warmtepompen samen**: één virtuele thermostaat stuurt een optionele waterwarmtepomp en een willekeurig aantal luchtwarmtepompen (assists).
- **Offsets en grenzen per apparaat**: aparte onder- en bovenoffsets voor verwarmen en koelen per apparaat, plus een globaal minimum en maximum setpoint.
- **Verwarmen en koelen**: luchtwarmtepompen die kunnen koelen doen mee in de koelmodus; de waterwarmtepomp doet niet mee met koelen.
- **Assists handmatig of automatisch**: jij bepaalt wanneer assists draaien, of PowerClimate zet ze aan en uit met timers en bescherming tegen pendelen.
- **Presets**: `none`, `boost`, `away`, `main only` (alleen de hoofdwarmtepomp) en `supply advice` (stuur de aanvoertemperatuur van de waterwarmtepomp naar een advieswaarde).
- **Thermostaat-mirroring**: setpointwijzigingen op gekozen thermostaten worden naar PowerClimate gekopieerd.
- **Diagnostiek**: een modussensor per warmtepomp, temperatuurverloop van ruimte en water, totaal vermogen en een diagnostiekdownload.
- **Alleen standaard services**: PowerClimate stuurt je bestaande `climate.*` entities via Home Assistant.

![De PowerClimate-thermostaat met HVAC-modus en preset.](docs/images/climate-more-info.png)

## Installatie

### HACS (aanbevolen)

1. Open in Home Assistant **HACS → Integraties → Custom repositories**.
2. Voeg de URL van deze repository toe en kies **Categorie** **Integration**.
3. Zoek **PowerClimate** en installeer het.
4. Herstart Home Assistant.

Pre-releases (alfa- en bètaversies) biedt HACS alleen aan als je die voor PowerClimate inschakelt.

### Handmatig

Kopieer `custom_components/powerclimate/` naar `config/custom_components/` van je Home Assistant en herstart Home Assistant.

## Setup

1. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → PowerClimate**.
2. Geef de hub een naam en kies een of meer ruimtetemperatuursensoren (PowerClimate gebruikt het gemiddelde van de beschikbare waarden).
3. Kies optioneel thermostaten om te mirroren. Alleen hun setpointwijzigingen worden naar PowerClimate gekopieerd; een gemirrorde thermostaat uitzetten zet PowerClimate niet uit.
4. Kies een optionele waterwarmtepomp (0 of 1) en nul of meer luchtwarmtepompen. De eerste gemirrorde thermostaat staat vooraf ingevuld als waterwarmtepomp.

   ![Water- en luchtwarmtepompen kiezen.](docs/images/config-select-devices.png)

5. Stel elke warmtepomp op een eigen pagina in: vermogenssensor, watertemperatuursensor (waterwarmtepomp), offsets voor verwarmen en koelen, en of PowerClimate hem aan en uit mag zetten.

   ![Een luchtwarmtepomp instellen.](docs/images/config-air-device.png)

Stel de onderste verwarmingsoffset zo in dat de warmtepomp bijna, maar niet helemaal stopt: met −3 °C is het setpoint minstens 17 °C als de warmtepomp zelf 20 °C meet.

Later wijzigen kan via de knop **Configureren** van de hub: setup en apparaten aanpassen, de geavanceerde opties afstellen of het experimentele aanvoeradvies instellen.

![Het optiemenu van een PowerClimate-hub.](docs/images/options-menu.png)

## Presets

| Preset | Waterwarmtepomp | Luchtwarmtepomp(en) |
|--------|-----------------|---------------------|
| **none** | Volgt het ruimtedoel binnen zijn offsets | Volgen het ruimtedoel als ze aan staan; blijven ongemoeid als ze uit staan (tenzij PowerClimate ze mag schakelen) |
| **boost** | Huidige temperatuur + bovenoffset | Aangezet (als dat mag) en op huidige temperatuur + bovenoffset gezet (koelen: + onderoffset) |
| **away** | Minimaal (huidige temperatuur + onderoffset); het ruimtedoel zakt naar het minimum setpoint | Uitgezet als dat mag, anders minimaal; in de koelmodus stijgt het ruimtedoel naar het maximum setpoint |
| **main only** | Zoals bij `none` | Alleen de hoofdwarmtepomp draait (de eerste luchtwarmtepomp als er geen waterwarmtepomp is); de andere worden uitgezet als dat mag, anders ongemoeid gelaten |
| **supply advice** | Het setpoint wordt zo gestuurd dat de gemeten aanvoertemperatuur een adviessensor volgt | Zoals bij `none` |

De preset aanvoeradvies verschijnt zodra je onder **Configureren → Experimenteel** een aanvoeradviessensor instelt.

## Sensoren

Elke hub is een apparaat met deze entities:

| Entity | Beschrijving |
|--------|--------------|
| Climate | De virtuele thermostaat; de attributen bevatten de volledige systeemstatus (ruimte, ETA, status per warmtepomp, assist-timers, aanvoerregeling) |
| HPx modus | Per warmtepomp: de modus waarin PowerClimate hem laat draaien (`off`, `minimal`, `setpoint`, `boost`, `supply_advice`), met zijn status als attributen |
| Temperatuurverloop | Verandering van de ruimtetemperatuur (°C/u) |
| Waterverloop | Verandering van de aanvoerwatertemperatuur (°C/u) |
| Totaal vermogen | Som van de ingestelde vermogenssensoren |
| Doeltemperatuur | Het ruimtedoel van PowerClimate als sensor |
| Aanvoercorrectie | Setpointcorrectie van de aanvoertemperatuurregeling |
| Kamercorrectie | Setpointcorrectie van de kamerregeling van de waterwarmtepomp (experimenteel) |

![De entities van een PowerClimate-hub.](docs/images/device-entities.png)

## Documentatie

- Detailed documentation (EN): [docs/README.md](docs/README.md)
- Gedetailleerde documentatie (NL): [docs/README-NL.md](docs/README-NL.md)
- Release notes: [CHANGELOG.md](CHANGELOG.md)

## Support

Issues en feature requests: gebruik de GitHub issue tracker die in de manifest van de integratie gelinkt is.
