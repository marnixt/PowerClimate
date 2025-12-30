# PowerClimate (NL)

Home Assistant integratie om meerdere warmtepompen te besturen en hun setpoints te coordineren met offsets voor iedere warmtepomp.

Niet gelieerd aan Home Assistant.

## Documentatie

- Gedetailleerde documentatie (NL): [custom_components/powerclimate/README-NL.md](custom_components/powerclimate/README-NL.md)
- Detailed documentation (EN): [custom_components/powerclimate/README.md](custom_components/powerclimate/README.md)

## Functies

- Multi-warmtepomp aansturing: één virtuele thermostaat stuurt een (hybride) water warmtepomp en coördineert meerdere ondersteunende warmtempompen.
- Ondersteunende warmtepompen: handmatig (default) of optioneel automatisch aan/uit (timers + anti-pendel).
- Grbruik overschot zonnepanelen (experimenteel): preset `Solar` kan vermogensbudgetten verdelen op basis van een “net power” sensor.
- Verschillende text-sensoren voor diagnostiek (thermische samenvatting, per-warmtepomp, etc).

## Installatie

### Installeren met HACS (aanbevolen)

1. HACS → **Integraties**.
2. Menu (⋮) → **Custom repositories**.
3. Voeg de repository-URL toe en kies categorie **Integration**.
4. Installeer **PowerClimate** en herstart Home Assistant.

### Handmatige installatie

1. Kopieer `custom_components/powerclimate/` naar je Home Assistant `config/custom_components/`.
2. Herstart Home Assistant.

## Setup

1. Home Assistant → **Instellingen → Apparaten & Diensten → Integratie toevoegen → PowerClimate**.
2. Kies één of meerdere ruimtesensoren (PowerClimate gebruikt het gemiddelde van beschikbare waarden).
3. Configureer HP1 en eventuele assist warmtepompen (HP2/HP3/…).

