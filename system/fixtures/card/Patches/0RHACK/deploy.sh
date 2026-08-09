#!/bin/sh

export USER_DIR=${USER_DIR:="/usbdrive"}
# PATCH_DIR=${PATCH_DIR:="/usbdrive/Patches"}
# FW_DIR=${FW_DIR:="/root"}
# SCRIPTS_DIR=$FW_DIR/scripts

oscsend localhost 4001 /oled/aux/line/2 s "installing"
oscsend localhost 4001 /oled/aux/line/3 s "0RHACK"

mkdir -p $USER_DIR/media/orhack
mkdir -p $USER_DIR/media/orhack/kits/kit-1
mkdir -p $USER_DIR/media/orhack/kits/kit-2
mkdir -p $USER_DIR/media/orhack/kits/kit-3
mkdir -p $USER_DIR/media/orhack/kits/kit-4
mkdir -p $USER_DIR/media/orhack/kits/kit-5
mkdir -p $USER_DIR/media/orhack/kits/kit-6
mkdir -p $USER_DIR/media/orhack/kits/kit-7
mkdir -p $USER_DIR/media/orhack/kits/kit-8
mkdir -p $USER_DIR/media/orhack/kits/kit-9
mkdir -p $USER_DIR/media/orhack/kits/kit-10
mkdir -p $USER_DIR/media/orhack/kits/kit-11
mkdir -p $USER_DIR/media/orhack/kits/kit-12
mkdir -p $USER_DIR/media/orhack/kits/kit-13
mkdir -p $USER_DIR/media/orhack/kits/kit-14
mkdir -p $USER_DIR/media/orhack/kits/kit-15
mkdir -p $USER_DIR/media/orhack/kits/kit-16
mkdir -p $USER_DIR/media/orhack/kits/kit-17
mkdir -p $USER_DIR/media/orhack/kits/kit-18
mkdir -p $USER_DIR/media/orhack/kits/kit-19
mkdir -p $USER_DIR/media/orhack/kits/kit-20
mkdir -p $USER_DIR/media/orhack/kits/kit-21
mkdir -p $USER_DIR/media/orhack/kits/kit-22
mkdir -p $USER_DIR/media/orhack/kits/kit-23
mkdir -p $USER_DIR/media/orhack/kits/kit-24
mkdir -p $USER_DIR/media/orhack/recordings
mkdir -p $USER_DIR/media/orhack/samples
mkdir -p $USER_DIR/media/orhack/user-modules/clocks
mkdir -p $USER_DIR/media/orhack/user-modules/effects/comp
mkdir -p $USER_DIR/media/orhack/user-modules/effects/delay
mkdir -p $USER_DIR/media/orhack/user-modules/effects/drive
mkdir -p $USER_DIR/media/orhack/user-modules/effects/filter
mkdir -p $USER_DIR/media/orhack/user-modules/effects/mod
mkdir -p $USER_DIR/media/orhack/user-modules/effects/reverb
mkdir -p $USER_DIR/media/orhack/user-modules/instruments/drum
mkdir -p $USER_DIR/media/orhack/user-modules/instruments/sampler
mkdir -p $USER_DIR/media/orhack/user-modules/instruments/synth
mkdir -p $USER_DIR/media/orhack/user-modules/mod-sources
mkdir -p $USER_DIR/media/orhack/user-modules/routers
mkdir -p $USER_DIR/media/orhack/user-modules/sequencers
mkdir -p $USER_DIR/media/orhack/user-modules/utility/audio
mkdir -p $USER_DIR/media/orhack/user-modules/utility/cv
mkdir -p $USER_DIR/media/orhack/user-modules/utility/midi
mkdir -p $USER_DIR/media/orhack/user-modules/utility/visual

mkdir -p $USER_DIR/data/orhack/presets
cp -r data/presets/*  $USER_DIR/data/orhack/presets
cp data/rack.json $USER_DIR/data/orhack

chmod 555 $USER_DIR/data/orhack/presets/Init

exit 0
