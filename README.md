[![Logo](resources/ui/splash_screen.png)](https://shdwp.github.io/ukraine/)

(Github Readme Banner and Splash screen Artwork by Andriy Dankovych, CC BY-SA 4.0)

# DCS Retribution - Danica Edition

This is the **Danica Edition** fork of [DCS Retribution](https://github.com/dcs-retribution/dcs-retribution), maintained for a weekly
multiplayer campaign. It tracks upstream Retribution and adds its own features on top.

[![GitHub issues](https://img.shields.io/github/issues/krazyj83/dcs-retribution-danica-edition)](https://github.com/krazyj83/dcs-retribution-danica-edition/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/krazyj83/dcs-retribution-danica-edition)](https://github.com/krazyj83/dcs-retribution-danica-edition/pulls)
[![Build](https://github.com/krazyj83/dcs-retribution-danica-edition/actions/workflows/build.yml/badge.svg?branch=dev)](https://github.com/krazyj83/dcs-retribution-danica-edition/actions)

### What this fork adds

* **Logistics**: base warehouses and weapon inventories; weapon cargo planned per LOGISTIC flight
  (Cargo tab, weight-checked, kneeboard load sheet, crates next to the aircraft, F10 cargo orders,
  crate-based delivery).
* **REDFOR AI**: need-based resupply by convoy or airlift, a main supply base, SHORAD convoy
  escorts after heavy BAI, and adaptive counters to the player's mission mix.
* **Naval**: ship weapons status and rearming at sea with naval munitions crates flown by
  helicopter.
* **Campaign**: player-drawn convoys that cost real units, strikeable motor pools, movable ships,
  frontline combat clusters and more. See the [changelog](changelog.md).

### Upstream DCS Retribution

[![Discord](https://img.shields.io/discord/1015931619187621999?label=Discord&logo=discord)](https://discord.gg/b4x34Bg4We)
![GitHub stars](https://img.shields.io/github/stars/dcs-retribution/dcs-retribution?style=social)

The sections below describe upstream DCS Retribution. Its Discord, wiki and releases are for
upstream builds, not this fork.

## About DCS Retribution 
(Last update: 2026-03-22)

DCS Retribution was forked in 2022 from [DCS Liberation](https://github.com/dcs-liberation/dcs_liberation),
which is a [DCS World](https://www.digitalcombatsimulator.com/en/products/world/) turn based single-player or co-op dynamic campaign. 
It is an external program that generates full and complex DCS missions and manage a persistent combat environment.

![Screenshot](https://user-images.githubusercontent.com/315852/120939254-0b4a9f80-c6cc-11eb-82f5-ce3f8d714bfe.png)

DCS Retribution is no longer relying on DCS Liberation updates,
though occasionally we might still sync a feature to our fork.
However, we are no longer backwards compatible with Liberation, and will no longer attempt to do so.

Instead, we are focussing on keeping our campaigns forward compatible so that you as a user
can continue on whatever campaign you had going on.
Please keep in mind that once you save a campaign that was started
in a previous (save-compatibility breaking) build, your save file
will have been migrated and thus no longer compatible with the previous build.
Therefore, we recommend backing up your saves and perhaps organizing them by version/build number.

In the past, we've relied very little on GitHub's "Releases" since our setup is rather based on
preview builds which are made easily available through our Discord server, where a channel
will trigger a message with a link to the latest preview build whenever we push a commit to the dev branch.
However, we're planning to change this strategy and attempt to publish a new release whenever DCS releases a new
version, unless it's a minor patch which doesn't require any changes on our end.

Over the years we've extended the original DCS Liberation with a lot of features, 
such as support for road-bases, neutral bases, weapon-settings, additional mission types, etc.
For a more complete overview of our features, check the
[changelog](https://github.com/dcs-retribution/dcs-retribution/blob/dev/changelog.md).

## Downloads

This fork: builds come from this repository's [GitHub Actions](https://github.com/krazyj83/dcs-retribution-danica-edition/actions)
(the `build-app` artifact of a green run on `dev`) and [releases](https://github.com/krazyj83/dcs-retribution-danica-edition/releases).

Upstream Retribution: https://github.com/dcs-retribution/dcs-retribution/releases, preview builds: https://github.com/dcs-retribution/dcs-retribution/wiki/Betas.

## DCS bugs

~~These DCS bugs prevent us from improving AI behavior. Please upvote them! (But please
_don't_ spam them with comments):~~

* ~~[A2A and SEAD escorts don't escort](https://forums.eagle.ru/topic/251798-options-for-alternate-ai-escort-behavior/?tab=comments#comment-4668033)~~
* ~~[DEAD can't use mixed loadouts effectively](https://forums.eagle.ru/topic/271941-ai-rtbs-after-firing-decoys-despite-full-load-of-bombs/)~~

While DCS bugs are still a thing, we don't quite agree with the ones stated above.
We believe to have addressed these, although some quirks still exist.
For example, SEAD Escorts tend to be a little picky with what they engage,
especially with older SAM systems.

## Bugs and feature requests

For this fork, report bugs and ideas on the
[Danica Edition issue tracker](https://github.com/krazyj83/dcs-retribution-danica-edition/issues).
Problems that also happen in upstream Retribution belong on the
[upstream bug tracker](https://github.com/dcs-retribution/dcs-retribution/issues).
In either case, please search first to see if it has already been reported.

## Roadmap

Upstream Retribution plans its work on its
[issue tracker](https://github.com/dcs-retribution/dcs-retribution/issues).
Features of this fork are listed in the [changelog](changelog.md).

## Resources

Tutorials, contributors and developer's guides are available in upstream Retribution's
[Wiki](https://github.com/dcs-retribution/dcs-retribution/wiki/)

(Some historical information is also available on
[Liberation's Wiki](https://github.com/dcs-liberation/dcs_liberation/wiki/))

## Special Thanks

First, a big thanks to shdwp, for starting the original DCS Liberation project. 

Then, DCS Liberation/Retribution uses [pydcs](https://github.com/pydcs/dcs) for mission generation, and nothing would be possible without this.
It also uses the popular [Mist](https://github.com/mrSkortch/MissionScriptingTools) lua framework for mission scripting. Support for the 
impressive [Moose](https://github.com/FlightControl-Master/MOOSE) framework was also introduced,
allowing for even more customization.

Excellent lua scripts DCS Liberation/Retribution uses as plugins:

* For the JTAC feature, DCS Retribution embeds Ciribob's JTAC Autolase [script](https://github.com/ciribob/DCS-JTACAutoLaze).
* Walder's [Skynet-IADS](https://github.com/walder/Skynet-IADS) is used for Integrated Air Defense System.
* Carstens Arty Spotter https://www.digitalcombatsimulator.com/en/files/3339128/ is an amazing force multiplyer to drop the hammer on enemies.
* MBot's [Call Artillery Script](https://forum.dcs.world/topic/310506-call-artillery-script/) uses in-map artillery and forward observers to enable artillery fire missions.

Please also show some support to these projects ! 
