// -------------------------------------------------------------------
// ------------------- DDJ-1000 script file v.0.99 -------------------
// -------------------------------------------------------------------

function PioneerDDJ1000() {}

// ============================================================
// DDJ-1000 Pioneer Unlock / Handshake (FNV1a32 Challenge-Response)
// ============================================================
if (typeof Math.imul === "undefined") {
    Math.imul = function(a, b) {
        var aHi = (a >>> 16) & 0xffff, aLo = a & 0xffff;
        var bHi = (b >>> 16) & 0xffff, bLo = b & 0xffff;
        return ((aLo * bLo) + (((aHi * bLo + aLo * bHi) << 16) >>> 0) | 0);
    };
}

var PioneerDDJ1000Unlock = {
    SECRET:    0x680131FB,
    FNV_BASIS: 0x811C9DC5,
    FNV_PRIME: 0x01000193,
    CHALLENGE_PREFIX_LEN: 33,
    handshakeAt: 0,
    cooldownMs:  2000,
    unlocked:    false,
    // The DDJ-1000 only accepts the 14 38 response if the whole SysEx arrives in ONE
    // USB bulk transfer. Mixxx (PortMidi -> ALSA seq -> snd-usbmidi) splits it into two
    // URBs (84 B + 4 B), so every handshake from here fails and leaves the DDJ in a
    // "11 02 ready" loop. Unlock is done before Mixxx by ddj1000-unlock@.service (udev);
    // the DDJ stays unlocked, this mapping only keeps the 200 ms heartbeat.
    // See ddj1000-linux-driver docs/session-log.md (2026-11-07, 22:03).
    handshakeEnabled: false,
    heartbeatEnabled: false,

    PRELUDE: [
        [0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x00,0x0B,
         0x2B,0x68,0x00,0x00,0x00,0x00,0xF7],
        [0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x00,0x0A,
         0x00,0x28,0x00,0x26,0x00,0x0A,0x39,0x4A,0x74,0x28,0x53,0x20,0x20,
         0x14,0x15,0x22,0x05,
         0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
         0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
         0x00,0x00,0x00,0x00,0x00,0xF7],
        [0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x00,0x0B,
         0x2B,0x68,0x00,0x00,0x00,0x00,0xF7],
        [0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x00,0x0C,
         0x00,0x00,0x02,0x0E,0x0E,0x00,0x00,0x00,0xF7]
    ],

    HANDSHAKE: [
        0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x12,0x2A,
        0x01,0x0B,0x50,0x69,0x6F,0x6E,0x65,0x65,0x72,0x44,0x4A,
        0x02,0x0B,0x72,0x65,0x6B,0x6F,0x72,0x64,0x62,0x6F,0x78,
        0x03,0x12,0x0C,0x0D,0x08,0x04,0x05,0x09,0x03,0x07,0x04,
        0x00,0x00,0x04,0x03,0x0E,0x00,0x0A,0xF7
    ],

    RESP_PREFIX: [
        0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x14,0x38,
        0x01,0x0B,0x50,0x69,0x6F,0x6E,0x65,0x65,0x72,0x44,0x4A,
        0x02,0x0B,0x72,0x65,0x6B,0x6F,0x72,0x64,0x62,0x6F,0x78,
        0x04,0x0A
    ],

    VENDOR: [0x08,0x07,0x0A,0x00,0x08,0x0E,0x0E,0x0A,0x0C,0x00,
             0x09,0x00,0x03,0x04,0x07,0x06,0x00,0x0B,0x09,0x00],

    CHALLENGE_PREFIX: [
        0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x13,0x2A,
        0x01,0x0B,0x50,0x69,0x6F,0x6E,0x65,0x65,0x72,0x44,0x4A,
        0x02,0x09,0x44,0x44,0x4A,0x31,0x30,0x30,0x30,0x04,0x0A
    ],

    fnv1a32: function(bytes) {
        var h = this.FNV_BASIS | 0;
        for (var i = 0; i < bytes.length; i++) {
            h = Math.imul(h ^ bytes[i], this.FNV_PRIME);
        }
        return h >>> 0;
    },

    spreadByte: function(arr, v) {
        arr.push((v >> 4) & 0x0F);
        arr.push(v & 0x0F);
    },

    extractSeedE: function(data) {
        var off = this.CHALLENGE_PREFIX_LEN + 10;
        var r = [];
        for (var i = 0; i < 8; i += 2) {
            var hi = data[off + i], lo = data[off + i + 1];
            if (hi > 0x0F || lo > 0x0F) return null;
            r.push((hi << 4) | lo);
        }
        return r.length === 4 ? r : null;
    },

    buildResponse: function(data) {
        var se = this.extractSeedE(data);
        if (!se) return null;
        var sv = ((se[0]<<24)|(se[1]<<16)|(se[2]<<8)|se[3]) >>> 0;
        var secret = (sv ^ this.SECRET) >>> 0;
        var inp = se.slice();
        inp.push((secret>>>24)&0xFF, (secret>>>16)&0xFF,
                 (secret>>>8)&0xFF,   secret&0xFF);
        var h = this.fnv1a32(inp);
        var resp = this.RESP_PREFIX.slice();
        this.spreadByte(resp, (h>>>24)&0xFF);
        this.spreadByte(resp, (h>>>16)&0xFF);
        this.spreadByte(resp, (h>>>8)&0xFF);
        this.spreadByte(resp, h&0xFF);
        resp.push(0x05, 0x16);
        for (var i = 0; i < this.VENDOR.length; i++) resp.push(this.VENDOR[i]);
        resp.push(0xF7);
        return resp;
    },

    sendHandshake: function() {
        if (!this.handshakeEnabled) {
            if (!this.handshakeSkipLogged) {
                print("DDJ-1000 Unlock: handshake disabled (unlock via ddj1000-unlock@.service)");
                this.handshakeSkipLogged = true;
            }
            return;
        }
        for (var i = 0; i < this.PRELUDE.length; i++) {
            midi.sendSysexMsg(this.PRELUDE[i], this.PRELUDE[i].length);
        }
        midi.sendSysexMsg(this.HANDSHAKE, this.HANDSHAKE.length);
        this.handshakeAt = Date.now();
        print("DDJ-1000 Unlock: handshake sent");
    },

    isReady: function(data, len) {
        var R = [0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x11,0x02,0xF7];
        if (len !== R.length) return false;
        for (var i = 0; i < R.length; i++) if (data[i] !== R[i]) return false;
        return true;
    },

    isChallenge: function(data, len) {
        if (len < this.CHALLENGE_PREFIX_LEN + 19) return false;
        for (var i = 0; i < this.CHALLENGE_PREFIX.length; i++) {
            if (data[i] !== this.CHALLENGE_PREFIX[i]) return false;
        }
        var t = this.CHALLENGE_PREFIX_LEN;
        return (data[len-1] === 0xF7 && data[t+8] === 0x03 && data[t+9] === 0x0A);
    }
};

PioneerDDJ1000.handleSysex = function(data, length) {
    if (PioneerDDJ1000Unlock.isReady(data, length)) {
        var now = Date.now();
        if (now - PioneerDDJ1000Unlock.handshakeAt >= PioneerDDJ1000Unlock.cooldownMs) {
            PioneerDDJ1000Unlock.sendHandshake();
        }
    } else if (PioneerDDJ1000Unlock.isChallenge(data, length)) {
        var bytes = [];
        for (var j = 0; j < length; j++) bytes.push(data[j]);
        var resp = PioneerDDJ1000Unlock.buildResponse(bytes);
        if (resp) {
            midi.sendSysexMsg(resp, resp.length);
            print("DDJ-1000 Unlock: challenge response sent, seedE=" +
                PioneerDDJ1000Unlock.extractSeedE(bytes).map(
                    function(b){return ("0"+b.toString(16)).slice(-2);}).join(""));
        }
    } else if (length >= 11 && data[9] === 0x15 && data[10] === 0x02) {
        PioneerDDJ1000Unlock.unlocked = true;
        print("DDJ-1000 Unlock: ACK 15 02 received - controller unlocked!");
    }
};

// Mixxx delivers every incoming SysEx message of a MIDI controller to
// <functionprefix>.incomingData(data, length); the XML <status>0xF0</status>
// binding is never called for SysEx. Route it to the unlock handler.
PioneerDDJ1000.incomingData = function(data, length) {
    PioneerDDJ1000.handleSysex(data, length);
};
// ============================================================


const defaultOn = 0x7F;
const defaultOff = 0x00;

const HC_dimmedColor = 64;
const HC_Color = 29;
const Black = 0;
const tempoRangePadColor = 39;
const tempoRangePadColorSelected = 44;

const Tempo6 = 0.06;
const Tempo10 = 0.10;
const Tempo16 = 0.16;
const Tempo25 = 0.25;
const Tempo50 = 0.50;
const Tempo100 = 1;

// For Job Blinking 
var jogIsONCH1 = 0;
var jogIsONCH2 = 0;
var jogIsONCH3 = 0;
var jogIsONCH4 = 0;

// Pad port

const HcCH1Port = 0x97; // Hotcue port CH1
const HcCH2Port = 0x99; // Hotcue port CH2
const HcCH3Port = 0x9B; // Hotcue port CH3
const HcCH4Port = 0x9D; // Hotcue port CH4

// For position Bar
const positionBarSpeedFactor = 25; // if == 1, the position bar is very slow...

// For Jog Time selection
var timeTypeCH1 = 0;
var timeTypeCH2 = 0;
var timeTypeCH3 = 0;
var timeTypeCH4 = 0;




// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Init / Shutdown funtion -------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------

	PioneerDDJ1000.init = function (id, debugging) {
		// Pioneer DSP SysEx Init
		// A (re)starting 50 01 heartbeat makes the DDJ open a new host session and ask for a
		// handshake (11 02 every second, spinner on the jog screens). Mixxx cannot complete that
		// handshake (SysEx split over two USB transfers), so with heartbeatEnabled=false the
		// session established by ddj1000-unlock@.service is kept instead. Test 2026-11-07 22:2x.
		if (PioneerDDJ1000Unlock.heartbeatEnabled) {
			midi.sendSysexMsg([0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x50,0x01,0xF7], 12);
		}
		midi.sendSysexMsg([0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x03,0x01,0xF7], 12);
		midi.sendSysexMsg([0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x0B,0x31,0x00,0x00,0x00,0x00,0xF7], 16);
		midi.sendSysexMsg([0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x0C,0x00,0x00,0x02,0x0E,0x0E,0x00,0x00,0x00,0xF7], 19);
		// Heartbeat alle 200ms - haelt DDJ-1000 DSP aktiv
		if (PioneerDDJ1000Unlock.heartbeatEnabled) {
			PioneerDDJ1000.heartbeatTimer = engine.beginTimer(200, function() {
				midi.sendSysexMsg([0xF0,0x00,0x40,0x05,0x00,0x00,0x02,0x00,0x00,0x50,0x01,0xF7], 12);
			});
		} else {
			print("DDJ-1000: heartbeat disabled (session kept from ddj1000-unlock@.service)");
		}
		PioneerDDJ1000.colorFxInit();
		PioneerDDJ1000.browseInit();
		var i = 0;
		
		// Play & Cue
		for (i=0;i < 5;i++) {

			midi.sendShortMsg(0x90+i,0x0B,defaultOff); // Play
			midi.sendShortMsg(0x90+i,0x0C,defaultOff); // Cue
		}
		
		// Hotcue off
		for (i=0;i < 7;i++) {	
			midi.sendShortMsg(0x97,i,Black);
		}
		
		// Loop Button
		for (i=0;i < 5;i++) {	
			midi.sendShortMsg(0x90+i,0x10,0x7F);
			midi.sendShortMsg(0x90+i,0x11,0x7F); // Loop Out
			midi.sendShortMsg(0x90+i,0x14,0x00);
		}
			

		// Init for tempo Range
			engine.setValue("[Channel1]", "rateRange", Tempo6);
			engine.setValue("[Channel2]", "rateRange", Tempo6);
			engine.setValue("[Channel3]", "rateRange", Tempo6);
			engine.setValue("[Channel4]", "rateRange", Tempo6);
		
			
		// Callback connections
		// ------ VuMeters
		engine.connectControl("[Channel1]","VuMeter","PioneerDDJ1000.LedVuMeterCH1");
		engine.connectControl("[Channel2]","VuMeter","PioneerDDJ1000.LedVuMeterCH2");
		engine.connectControl("[Channel3]","VuMeter","PioneerDDJ1000.LedVuMeterCH3");
		engine.connectControl("[Channel4]","VuMeter","PioneerDDJ1000.LedVuMeterCH4");
		
		// ------ Loop
		// Enabled callbacks
		engine.connectControl("[Channel1]","loop_enabled","PioneerDDJ1000.LoopSetFeedbackCH1");
		engine.connectControl("[Channel2]","loop_enabled","PioneerDDJ1000.LoopSetFeedbackCH2");
		engine.connectControl("[Channel3]","loop_enabled","PioneerDDJ1000.LoopSetFeedbackCH3");
		engine.connectControl("[Channel4]","loop_enabled","PioneerDDJ1000.LoopSetFeedbackCH4");
		
		// ------ Track Time
		engine.connectControl("[Channel1]", "playposition","PioneerDDJ1000.TrackTimeUpdateChannel1");
		engine.connectControl("[Channel2]", "playposition","PioneerDDJ1000.TrackTimeUpdateChannel2");
		engine.connectControl("[Channel3]", "playposition","PioneerDDJ1000.TrackTimeUpdateChannel3");
		engine.connectControl("[Channel4]", "playposition","PioneerDDJ1000.TrackTimeUpdateChannel4");
		
		// ------ Actual BPM & Tempo range On Jog
		engine.connectControl("[Channel1]","bpm","PioneerDDJ1000.BpmOnJogCH1"); // Update Bpm + Tempo Range
		engine.connectControl("[Channel2]","bpm","PioneerDDJ1000.BpmOnJogCH2");
		engine.connectControl("[Channel3]","bpm","PioneerDDJ1000.BpmOnJogCH3");
		engine.connectControl("[Channel4]","bpm","PioneerDDJ1000.BpmOnJogCH4");
		
		// Timer
		// ------ End of track blinking
		engine.beginTimer(250,"PioneerDDJ1000.EndOfTrackBlink()");
	
		// Proactive unlock handshake (DDJ needs this before challenge)
		PioneerDDJ1000Unlock.sendHandshake();
		PioneerDDJ1000.HotCueTriggerInit();
		
		// Jog Information on
		for (i=0;i < 4;i++) {
			midi.sendShortMsg(0x90+i,0x5D,0x00);
			midi.sendShortMsg(0x90+i,0x5B,0x01);
		}
		
	};
	
	PioneerDDJ1000.shutdown = function() {
		var i = 0;
		if (PioneerDDJ1000.heartbeatTimer) engine.stopTimer(PioneerDDJ1000.heartbeatTimer);
		for (i=0;i < 5;i++) {
			midi.sendShortMsg(0x90+i,0x0B,defaultOff); // Play
			midi.sendShortMsg(0x90+i,0x0C,defaultOff); // Cue
		}
		
		for (i=0;i < 8;i++) {	
			midi.sendShortMsg(0x97,i,Black);
		}
		
		// Loop Button
		for (i=0;i < 5;i++) {	
			midi.sendShortMsg(0x90+i,0x10,0x00);
			midi.sendShortMsg(0x90+i,0x11,0x00); // Loop Out
			midi.sendShortMsg(0x90+i,0x14,0x00);
		}
		
			
		engine.stopTimer("PioneerDDJ1000.EndOfTrackBlink()");
		
		// Jog Information off
		for (i=0;i < 4;i++) {
			midi.sendShortMsg(0x90+i,0x5B,0x00);
			midi.sendShortMsg(0x90+i,0x5D,0x7F);
		}
		
	};
	
// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Functions for init ------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------
	
	// -------------- HotCue
	PioneerDDJ1000.HotCueTriggerInit = function () {	// Callback setting for Hotcue illumation
		
		// Hotcue illumination triggers - CH1
		engine.connectControl("[Channel1]","hotcue_1_enabled","PioneerDDJ1000.HotCue1TriggerCH1");// HotCues 1 CH1
		engine.connectControl("[Channel1]","hotcue_2_enabled","PioneerDDJ1000.HotCue2TriggerCH1");// HotCues 2 CH1
		engine.connectControl("[Channel1]","hotcue_3_enabled","PioneerDDJ1000.HotCue3TriggerCH1");// HotCues 3 CH1
		engine.connectControl("[Channel1]","hotcue_4_enabled","PioneerDDJ1000.HotCue4TriggerCH1");// HotCues 4 CH1
		engine.connectControl("[Channel1]","hotcue_5_enabled","PioneerDDJ1000.HotCue5TriggerCH1");// HotCues 5 CH1
		engine.connectControl("[Channel1]","hotcue_6_enabled","PioneerDDJ1000.HotCue6TriggerCH1");// HotCues 6 CH1
		engine.connectControl("[Channel1]","hotcue_7_enabled","PioneerDDJ1000.HotCue7TriggerCH1");// HotCues 7 CH1
		engine.connectControl("[Channel1]","hotcue_8_enabled","PioneerDDJ1000.HotCue8TriggerCH1");// HotCues 8 CH1
		
		// Hotcue illumination triggers - CH2
		engine.connectControl("[Channel2]","hotcue_1_enabled","PioneerDDJ1000.HotCue1TriggerCH2");// HotCues 1 CH2
		engine.connectControl("[Channel2]","hotcue_2_enabled","PioneerDDJ1000.HotCue2TriggerCH2");// HotCues 2 CH2
		engine.connectControl("[Channel2]","hotcue_3_enabled","PioneerDDJ1000.HotCue3TriggerCH2");// HotCues 3 CH2
		engine.connectControl("[Channel2]","hotcue_4_enabled","PioneerDDJ1000.HotCue4TriggerCH2");// HotCues 4 CH2
		engine.connectControl("[Channel2]","hotcue_5_enabled","PioneerDDJ1000.HotCue5TriggerCH2");// HotCues 5 CH2
		engine.connectControl("[Channel2]","hotcue_6_enabled","PioneerDDJ1000.HotCue6TriggerCH2");// HotCues 6 CH2
		engine.connectControl("[Channel2]","hotcue_7_enabled","PioneerDDJ1000.HotCue7TriggerCH2");// HotCues 7 CH2
		engine.connectControl("[Channel2]","hotcue_8_enabled","PioneerDDJ1000.HotCue8TriggerCH2");// HotCues 8 CH2
		
		// Hotcue illumination triggers - CH3
		engine.connectControl("[Channel3]","hotcue_1_enabled","PioneerDDJ1000.HotCue1TriggerCH3");// HotCues 1 CH3
		engine.connectControl("[Channel3]","hotcue_2_enabled","PioneerDDJ1000.HotCue2TriggerCH3");// HotCues 2 CH3
		engine.connectControl("[Channel3]","hotcue_3_enabled","PioneerDDJ1000.HotCue3TriggerCH3");// HotCues 3 CH3
		engine.connectControl("[Channel3]","hotcue_4_enabled","PioneerDDJ1000.HotCue4TriggerCH3");// HotCues 4 CH3
		engine.connectControl("[Channel3]","hotcue_5_enabled","PioneerDDJ1000.HotCue5TriggerCH3");// HotCues 5 CH3
		engine.connectControl("[Channel3]","hotcue_6_enabled","PioneerDDJ1000.HotCue6TriggerCH3");// HotCues 6 CH3
		engine.connectControl("[Channel3]","hotcue_7_enabled","PioneerDDJ1000.HotCue7TriggerCH3");// HotCues 7 CH3
		engine.connectControl("[Channel3]","hotcue_8_enabled","PioneerDDJ1000.HotCue8TriggerCH3");// HotCues 8 CH3
		
		// Hotcue illumination triggers - CH4
		engine.connectControl("[Channel4]","hotcue_1_enabled","PioneerDDJ1000.HotCue1TriggerCH4");// HotCues 1 CH4
		engine.connectControl("[Channel4]","hotcue_2_enabled","PioneerDDJ1000.HotCue2TriggerCH4");// HotCues 2 CH4
		engine.connectControl("[Channel4]","hotcue_3_enabled","PioneerDDJ1000.HotCue3TriggerCH4");// HotCues 3 CH4
		engine.connectControl("[Channel4]","hotcue_4_enabled","PioneerDDJ1000.HotCue4TriggerCH4");// HotCues 4 CH4
		engine.connectControl("[Channel4]","hotcue_5_enabled","PioneerDDJ1000.HotCue5TriggerCH4");// HotCues 5 CH4
		engine.connectControl("[Channel4]","hotcue_6_enabled","PioneerDDJ1000.HotCue6TriggerCH4");// HotCues 6 CH4
		engine.connectControl("[Channel4]","hotcue_7_enabled","PioneerDDJ1000.HotCue7TriggerCH4");// HotCues 7 CH4
		engine.connectControl("[Channel4]","hotcue_8_enabled","PioneerDDJ1000.HotCue8TriggerCH4");// HotCues 8 CH4
	};




// ---------------------------------------------------------------------------------------------------------------
// ------------------------- All propose functions ---------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------

	PioneerDDJ1000.ColorTrigger = function (value, midiPort, midiNumber, OnColor, OffColor) {	// For callback functions dimmed LED
		if (value == 1) { // if touch pressed
			midi.sendShortMsg(midiPort,midiNumber,OnColor);
			midi.sendShortMsg(midiPort+1,midiNumber,OnColor); // For Shift illumination
		} else { // if touch released
			midi.sendShortMsg(midiPort,midiNumber,OffColor);
			midi.sendShortMsg(midiPort+1,midiNumber,OffColor); // For Shift illumination
		}
	};
	
	PioneerDDJ1000.sensitivityMinimizer = function (value, factor) { // factor must be lower than value !!!
		return (value/factor);
	};

	PioneerDDJ1000.sensitivityMaximizer = function (value, factor) { // factor value not to high !!!
		return (value*factor);
	};
	
	// Dimmed function
	PioneerDDJ1000.DimButton = function (value, midiPort, midiNumber, dimColor, normalColor) {	
		if (value == 0x7F) { // if touch pressed
			midi.sendShortMsg(midiPort,midiNumber,dimColor);
		} else { // if touch released
			midi.sendShortMsg(midiPort,midiNumber,normalColor);
		}
	};


// ---------------------------------------------------------------------------------------------------------------
// ------------------------- HotCue Illumination -----------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------


	// ---- CH 1
	PioneerDDJ1000.HotCue1TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x00, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue2TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x01, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue3TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x02, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue4TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x03, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue5TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x04, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue6TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x05, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue7TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x06, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue8TriggerCH1 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH1Port, 0x07, HC_Color, Black);
	};
	
	// ---- CH 2
	PioneerDDJ1000.HotCue1TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x00, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue2TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x01, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue3TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x02, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue4TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x03, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue5TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x04, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue6TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x05, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue7TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x06, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue8TriggerCH2 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH2Port, 0x07, HC_Color, Black);
	};
	
	// ---- CH 3
	PioneerDDJ1000.HotCue1TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x00, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue2TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x01, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue3TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x02, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue4TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x03, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue5TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x04, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue6TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x05, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue7TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x06, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue8TriggerCH3 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x07, HC_Color, Black);
	};
	
	// ---- CH 4
	PioneerDDJ1000.HotCue1TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x00, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue2TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x01, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue3TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x02, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue4TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x03, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue5TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x04, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue6TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x05, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue7TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x06, HC_Color, Black);
	};
	
	PioneerDDJ1000.HotCue8TriggerCH4 = function (value, group, control) {
		PioneerDDJ1000.ColorTrigger (value, HcCH3Port, 0x07, HC_Color, Black);
	};
	
	
	
	// PioneerDDJ1000.HotCueTouch -> Pads have to be dimmed ?
	PioneerDDJ1000.HotCueTouch = function (channel, control, value, status, group) {
		
		switch (control) { // DimOnly if Hotcue is set
			case 0 :	if (engine.getValue(group, "hotcue_1_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 1 :	if (engine.getValue(group, "hotcue_2_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 2 :	if (engine.getValue(group, "hotcue_3_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 3 :	if (engine.getValue(group, "hotcue_4_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 4 :	if (engine.getValue(group, "hotcue_5_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 5 :	if (engine.getValue(group, "hotcue_6_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 6 :	if (engine.getValue(group, "hotcue_7_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
			case 7 :	if (engine.getValue(group, "hotcue_8_enabled")) {
							PioneerDDJ1000.DimButton(value, status, control, HC_dimmedColor, HC_Color);
						}
						break;
		}
	};
	
	

// ---------------------------------------------------------------------------------------------------------------
// ------------------------- PreFader Level ----------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------

	PioneerDDJ1000.LedVuMeterCH1 = function (value, group, control) {
		midi.sendShortMsg(0xB0,0x02,value*127);
	};
	
	PioneerDDJ1000.LedVuMeterCH2 = function (value, group, control) {
		midi.sendShortMsg(0xB1,0x02,value*127);
	};
	
	PioneerDDJ1000.LedVuMeterCH3 = function (value, group, control) {
		midi.sendShortMsg(0xB2,0x02,value*127);
	};
	
	PioneerDDJ1000.LedVuMeterCH4 = function (value, group, control) {
		midi.sendShortMsg(0xB3,0x02,value*127);
	};



// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Scratch, Pitch bend -----------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------

	// For the button that enables/disables scratching
    PioneerDDJ1000.wheelTouch = function (channel, control, value, status, group) {  
        var deckNumber = script.deckFromGroup(group);
      if (value == 0x7F) { 
            var alpha = 1.0/8;
            var beta = alpha/32;
            engine.scratchEnable(deckNumber, 32767, 33+1/3, alpha, beta);
        } else {    // If button up
            engine.scratchDisable(deckNumber);
        }
    };
     
    // The wheel that actually controls the scratching
    PioneerDDJ1000.wheelTurn = function (channel, control, value, status, group) { 
        var newValue = value - 64;
        var deckNumber = script.deckFromGroup(group);
		
        if (engine.isScratching(deckNumber)) {
            engine.scratchTick(deckNumber, PioneerDDJ1000.sensitivityMaximizer(newValue,1.5)); // Scratch!
        } else {
			engine.setValue(group, 'jog', PioneerDDJ1000.sensitivityMinimizer(newValue,16)); // Pitch bend
        }
    };
	
	
	
// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Jog illumination and Information ----------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------
	
	// ----- End of Track Warning
	
	PioneerDDJ1000.EndOfTrackBlink  = function () { // call function for blinking, spare "timer"
		PioneerDDJ1000.EndOfTrackBlinkCH1();
		PioneerDDJ1000.EndOfTrackBlinkCH2();
		PioneerDDJ1000.EndOfTrackBlinkCH3();
		PioneerDDJ1000.EndOfTrackBlinkCH4();
	};
	
	PioneerDDJ1000.EndOfTrackBlinkCH1 = function () {
		if (engine.getValue("[Channel1]","end_of_track")) {
			if (jogIsONCH1) {
				midi.sendShortMsg(0x90,0x5B,0x01);
				jogIsONCH1 = 0;
			} else {
				midi.sendShortMsg(0x90,0x5B,0x00);
				jogIsONCH1 = 1;
			}
		} else {
			midi.sendShortMsg(0x90,0x5B,0x01);
		}
	};
	
	PioneerDDJ1000.EndOfTrackBlinkCH2 = function () {
		if (engine.getValue("[Channel2]","end_of_track")) {
			if (jogIsONCH2) {
				midi.sendShortMsg(0x91,0x5B,0x01);
				jogIsONCH2 = 0;
			} else {
				midi.sendShortMsg(0x91,0x5B,0x00);
				jogIsONCH2 = 1;
			}
		} else {
			midi.sendShortMsg(0x91,0x5B,0x01);
		}
	};
	
	PioneerDDJ1000.EndOfTrackBlinkCH3 = function () {
		if (engine.getValue("[Channel3]","end_of_track")) {
			if (jogIsONCH3) {
				midi.sendShortMsg(0x92,0x5B,0x01);
				jogIsONCH3 = 0;
			} else {
				midi.sendShortMsg(0x92,0x5B,0x00);
				jogIsONCH3 = 1;
			}
		} else {
			midi.sendShortMsg(0x92,0x5B,0x01);
		}
	};
	
	PioneerDDJ1000.EndOfTrackBlinkCH4 = function () {
		if (engine.getValue("[Channel4]","end_of_track")) {
			if (jogIsONCH4) {
				midi.sendShortMsg(0x93,0x5B,0x01);
				jogIsONCH4 = 0;
			} else {
				midi.sendShortMsg(0x93,0x5B,0x00);
				jogIsONCH4 = 1;
			}
		} else {
			midi.sendShortMsg(0x93,0x5B,0x01);
		}
	};
	
	
	// ----- Time
	
	PioneerDDJ1000.TrackTimeUpdateChannel1 = function (value, group, control){    // For channel 1
		PioneerDDJ1000.TrackTimeDisplay(1, value, group, timeTypeCH1);
	};
	
	PioneerDDJ1000.TrackTimeUpdateChannel2 = function (value, group, control){    // For channel 2
		PioneerDDJ1000.TrackTimeDisplay(2, value, group, timeTypeCH2);
	};
	
	PioneerDDJ1000.TrackTimeUpdateChannel3 = function (value, group, control){    // For channel 3
		PioneerDDJ1000.TrackTimeDisplay(3, value, group, timeTypeCH3);
	};
	
	PioneerDDJ1000.TrackTimeUpdateChannel4 = function (value, group, control){    // For channel 4
		PioneerDDJ1000.TrackTimeDisplay(4, value, group, timeTypeCH4);	
	};
	
	PioneerDDJ1000.TrackTimeDisplay = function (channel, value, group, timeType) {
		
		var midiPort = 0x90 + (channel-1);
		var trackDuration = engine.getValue(group, "duration"); // get total time
		var timeLeft = trackDuration * (1.0 - value); // compute time left
		var actualTime = trackDuration * value;
		var minutesLeft = timeLeft/60; 
		var secondesLeft = timeLeft%60; // modulo to get seconde...
		var actualMinutes = actualTime/60; 
		var actualSecondes = actualTime%60; // modulo to get seconde...
		
		if (timeType) { // True -> remaining time ; False -> elapsed time
			midi.sendShortMsg(midiPort,0x44,0x7F); // Show "minus"
			midi.sendShortMsg(midiPort,0x42,minutesLeft); // send minutes
			midi.sendShortMsg(midiPort,0x43,secondesLeft); // send secondes
		} else {
			midi.sendShortMsg(midiPort,0x44,0x00); // Hide "minus"
			midi.sendShortMsg(midiPort,0x42,actualMinutes); // send minutes
			midi.sendShortMsg(midiPort,0x43,actualSecondes); // send secondes
		}
		
		PioneerDDJ1000.CurrentPositionBarUpdate(channel,actualSecondes); // Update Position Bar for channel 4
	};
	
	PioneerDDJ1000.CurrentPositionBarUpdate = function (channelNumber,value){ // David Goodenough
		var currentBarPosition = value*9*positionBarSpeedFactor;
		var channelNbrCode = 176+(channelNumber-1);
		var valueOnA360Circle = currentBarPosition%360;
		var MSB = Math.floor(valueOnA360Circle/128);
		var LSB = valueOnA360Circle - (128*MSB);
		
		midi.sendShortMsg(channelNbrCode,0x14,MSB);
		midi.sendShortMsg(channelNbrCode,0x34,LSB);
		
	};
	
	PioneerDDJ1000.TimeTypeChangeGlobal = function (channel, control, value, status, group) { 
		if (value == 0x7F) {
			switch (status) {
				case 0x90 : PioneerDDJ1000.TimeTypeChange(1); break;
				case 0x91 : PioneerDDJ1000.TimeTypeChange(2); break;
				case 0x92 : PioneerDDJ1000.TimeTypeChange(3); break;
				case 0x93 : PioneerDDJ1000.TimeTypeChange(4); break;
			}
		}
	};
	
	
	PioneerDDJ1000.TimeTypeChange = function (channel) {
		
		if (channel == 1) {
			switch (timeTypeCH1) {
				case 0 : timeTypeCH1 = 1; break;
				case 1 : timeTypeCH1 = 0; break;
				default : timeTypeCH1 = 0; break;
			}
		}
		
		if (channel == 2) {
			switch (timeTypeCH2) {
				case 0 : timeTypeCH2 = 1; break;
				case 1 : timeTypeCH2 = 0; break;
				default : timeTypeCH2 = 0; break;
			}
		}
		
		if (channel == 3) {
			switch (timeTypeCH3) {
				case 0 : timeTypeCH3 = 1; break;
				case 1 : timeTypeCH3 = 0; break;
				default : timeTypeCH3 = 0; break;
			}
		}
		
		if (channel == 4) {
			switch (timeTypeCH4) {
				case 0 : timeTypeCH4 = 1; break;
				case 1 : timeTypeCH4 = 0; break;
				default : timeTypeCH4 = 0; break;
			}
		}
		
	};
	
	
	// ----- Rate range & Track Tempo display
	
	PioneerDDJ1000.BpmOnJogCH1 = function (value, group, control) {  // For Track BPM and Pitch range
		PioneerDDJ1000.DisplayBpmAndPitchRange(1, value, group); // Display Bpm 
	};
	
	PioneerDDJ1000.BpmOnJogCH2 = function (value, group, control) {  // For Track BPM and Pitch range
		PioneerDDJ1000.DisplayBpmAndPitchRange(2, value, group); // Display Bpm 
	};
	
	PioneerDDJ1000.BpmOnJogCH3 = function (value, group, control) {  // For Track BPM and Pitch range
		PioneerDDJ1000.DisplayBpmAndPitchRange(3, value, group); // Display Bpm 
	};
	
	PioneerDDJ1000.BpmOnJogCH4 = function (value, group, control) {  // For Track BPM and Pitch range
		PioneerDDJ1000.DisplayBpmAndPitchRange(4, value, group); // Display Bpm 
	};
	
	PioneerDDJ1000.DisplayBpmAndPitchRange = function (channel, value, group) {
		
		var midiPort = 0xB0 + (channel-1);
		var absoluteBPM = Math.floor(value*10);
		var actualTempo = engine.getValue(group,"rateRange");
		var actualRate = engine.getValue(group, "rate");
		var absolutePitchRange = Math.floor(((actualTempo * 10) * actualRate) * 100);
		var adaptPitchRange = 0;
		var MSB = 0;
		var LSB = 0;
		
		// Bpm value update
		
		if (value == 0) {
			MSB = 0;
			LSB = 0;
		} else {
			MSB = Math.floor(absoluteBPM / 128);
			LSB = absoluteBPM % 128;
		}
		
		midi.sendShortMsg(midiPort,0x15,MSB);
		midi.sendShortMsg(midiPort,0x35,LSB);
		
		// Pitch Range update

		if (absolutePitchRange < 0) {
			adaptPitchRange = 1000 - absolutePitchRange;
			MSB = Math.floor(adaptPitchRange / 128);
			LSB = adaptPitchRange % 128;
		} else {
			adaptPitchRange = 1000 + absolutePitchRange;
			MSB = Math.floor(adaptPitchRange / 128);
			LSB = adaptPitchRange % 128;
		}
		
		midi.sendShortMsg(midiPort,0x16,MSB);
		midi.sendShortMsg(midiPort,0x36,LSB);
	};
	
	
		
// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Loop State --------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------
	
	PioneerDDJ1000.DimLoopButton = function (channel, control, value, status, group) {
		PioneerDDJ1000.DimButton(value, status, control, 0, 0x7F);
	};
	
	PioneerDDJ1000.LoopSetFeedbackCH1 = function (value, group, control) {
		midi.sendShortMsg(0x90,0x14,value ? 0x7F : 0x00);
	};
	
	PioneerDDJ1000.LoopSetFeedbackCH2 = function (value, group, control) {
		midi.sendShortMsg(0x91,0x14,value ? 0x7F : 0x00);
	};
	
	PioneerDDJ1000.LoopSetFeedbackCH3 = function (value, group, control) {
		midi.sendShortMsg(0x92,0x14,value ? 0x7F : 0x00);
	};
	
	PioneerDDJ1000.LoopSetFeedbackCH4 = function (value, group, control) {
		midi.sendShortMsg(0x93,0x14,value ? 0x7F : 0x00);
	};
	
	PioneerDDJ1000.LoopScaleDividePer2CH1 = function (channel, control, value, status, group) {
		
		var isLoopEnabled = engine.getValue("[Channel1]","loop_enabled");
		//var actualLoopScale = engine.getValue("[Channel1]","loop_scale");
		
		if (value == 0x7F) {
		
			if (isLoopEnabled) {	// If Loop is already set
				engine.setValue("[Channel1]","loop_halve",1); // Didn't work, I don't know why
			} else {
				engine.setValue("[Channel1]","loop_in",1);
			}
		
		}
		
	};
	
	PioneerDDJ1000.LoopScaleMultiplyPer2CH1 = function (channel, control, value, status, group) {
	
		var isLoopEnabled = engine.getValue(group,"loop_enabled");
		//var actualLoopScale = engine.getValue("[Channel1]","loop_scale");
		
		if (value == 0x7F) {
		
			if (isLoopEnabled) {	// If Loop is already set
				engine.setValue(group,"loop_double",1);	// Didn't work, I don't know why
			}else {
				engine.setValue(group,"loop_out",1);
			}
		
		}
		
	};
		

// ---------------------------------------------------------------------------------------------------------------
// ------------------------- Rate Range Selector ----------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------

	PioneerDDJ1000.RangeSelector = function (channel, control, value, status, group) {
		if (value == 0x7F) {
			switch(engine.getValue(group,"rateRange")) {
				case Tempo6: engine.setValue(group,"rateRange",Tempo10); break;
				case Tempo10: engine.setValue(group,"rateRange",Tempo16); break;
				case Tempo16: engine.setValue(group,"rateRange",Tempo25); break;
				case Tempo25: engine.setValue(group,"rateRange",Tempo50); break;
				case Tempo50: engine.setValue(group,"rateRange",Tempo100); break;
				case Tempo100: engine.setValue(group,"rateRange",Tempo6); break;
			}
		}
	};


// ============================================================
// Mixer / Beat FX additions (ddj1000-linux-driver, 2026-11-07)
// MIDI numbers measured on the device via usbmon:
//   Filter CH1..4      B6 17..1A (MSB) / B6 37..3A (LSB)   -> XML, 14 bit
//   Beat FX LEVEL      B4 02 / B4 22                         -> XML, 14 bit
//   Beat FX ON/OFF     94 47                                 -> beatFxOnOff
//   Beat FX select     94 20/21/22 (3-phase rotary)          -> beatFxSelect
//   Sync deck 1..4     90..93 58                             -> XML sync_enabled
// ============================================================
PioneerDDJ1000.BEAT_FX_EFFECT = "[EffectRack1_EffectUnit1_Effect1]";

PioneerDDJ1000.beatFxOnOff = function(channel, control, value, status, group) {
    if (value !== 0x7F) {
        return;
    }
    var on = !engine.getValue(PioneerDDJ1000.BEAT_FX_EFFECT, "enabled");
    engine.setValue(PioneerDDJ1000.BEAT_FX_EFFECT, "enabled", on);
    midi.sendShortMsg(0x94, 0x47, on ? 0x7F : 0x00);
};

PioneerDDJ1000.beatFxSelectLast = -1;
PioneerDDJ1000.beatFxSelect = function(channel, control, value, status, group) {
    if (value !== 0x7F) {
        return;
    }
    // The selector reports its detent as one of three notes (0x20, 0x21, 0x22) in a cycle;
    // the step from the previous note gives the direction.
    var pos = control - 0x20;
    var last = PioneerDDJ1000.beatFxSelectLast;
    PioneerDDJ1000.beatFxSelectLast = pos;
    if (last < 0) {
        return;
    }
    var step = (pos - last + 3) % 3;
    if (step === 1) {
        engine.setValue(PioneerDDJ1000.BEAT_FX_EFFECT, "next_effect", 1);
    } else if (step === 2) {
        engine.setValue(PioneerDDJ1000.BEAT_FX_EFFECT, "prev_effect", 1);
    }
};

// Beat FX channel select (rotary, clockwise: SP MIC 3 1 2 4 MASTER). Each detent sends
// note-on 0x7F for the new position: 94 10=CH1 11=CH2 12=CH3 13=CH4 14=MASTER 15=MIC 16=SP.
// Routes [EffectRack1_EffectUnit1] exclusively to the selected target.
PioneerDDJ1000.BEAT_FX_UNIT = "[EffectRack1_EffectUnit1]";
PioneerDDJ1000.beatFxTargets = function(control) {
    switch (control) {
    case 0x10: return ["[Channel1]"];
    case 0x11: return ["[Channel2]"];
    case 0x12: return ["[Channel3]"];
    case 0x13: return ["[Channel4]"];
    case 0x14: return ["[Master]"];
    case 0x15: return ["[Microphone]"];
    case 0x16: return PioneerDDJ1000.samplerGroups();
    }
    return [];
};
PioneerDDJ1000.samplerGroups = function() {
    var count = engine.getValue("[App]", "num_samplers") || engine.getValue("[Master]", "num_samplers") || 0;
    var groups = [];
    for (var i = 1; i <= count; i++) {
        groups.push("[Sampler" + i + "]");
    }
    return groups;
};
PioneerDDJ1000.beatFxChannelSelect = function(channel, control, value, status, group) {
    if (value !== 0x7F) {
        return;
    }
    var all = ["[Channel1]", "[Channel2]", "[Channel3]", "[Channel4]", "[Master]", "[Microphone]"]
        .concat(PioneerDDJ1000.samplerGroups());
    var targets = PioneerDDJ1000.beatFxTargets(control);
    for (var i = 0; i < all.length; i++) {
        engine.setValue(PioneerDDJ1000.BEAT_FX_UNIT, "group_" + all[i] + "_enable",
            targets.indexOf(all[i]) >= 0 ? 1 : 0);
    }
    // Diagnostics (temporary, 2026-11-08)
    var u = PioneerDDJ1000.BEAT_FX_UNIT, st = "DDJ-1000 BeatFX route 0x" + control.toString(16) + ":";
    for (var j = 0; j < 6; j++) { st += " " + all[j] + "=" + engine.getValue(u, "group_" + all[j] + "_enable"); }
    st += " unit.enabled=" + engine.getValue(u, "enabled") + " unit.mix=" + engine.getValue(u, "mix").toFixed(2) +
        " fx.enabled=" + engine.getValue(PioneerDDJ1000.BEAT_FX_EFFECT, "enabled") +
        " fx.loaded=" + engine.getValue(PioneerDDJ1000.BEAT_FX_EFFECT, "loaded");
    print(st);
};

// ============================================================
// Sound Color FX (ddj1000-linux-driver, 2026-11-08)
// Buttons, measured with aseqdump: 96 00=DUB ECHO 01=PITCH 02=NOISE 03=FILTER.
// The DDJ does the radio selection itself: a press sends note-off (0x86) for the previously
// lit button, then note-on (0x96) for the new one; pressing the lit button only sends note-off.
// Selection loads the chain preset on all four QuickEffect chains; the COLOR knobs (super1,
// XML) then drive it. Nothing selected -> chains disabled, knobs without effect (Pioneer).
// Indices = 0-based position in Preferences > Effects > Quick Effect chain presets
// (2.5.3: EffectChainPresetManager::quickEffectPresetAtIndex). Reordering that list
// changes them; colorFxInit prints the index of the preset loaded at startup.
// ============================================================
PioneerDDJ1000.COLOR_FX_PRESETS = {
    // Index 0 is the empty preset ("---"); the list from effects.xml starts at 1.
    // Verified 2026-11-08 by parameter fingerprints in mixxx.log: 3=Loudness, 6=Echoverb HP, 14=Echo.
    0x00: {name: "Filter Echo", index: 7},   // DUB ECHO
    // 0x01 PITCH: intentionally unassigned (Pitch Shift destabilised audio, 2026-11-08) -> Color FX off
    0x02: {name: "White Noise", index: 1, bipolar: true},   // NOISE: center silent, both sides noise
    0x03: {name: "Filter", index: 15},       // FILTER
};
PioneerDDJ1000.COLOR_FX_DEFAULT = 0x03;
PioneerDDJ1000.colorFxSelected = -1;

PioneerDDJ1000.quickFxGroup = function(deck) {
    return "[QuickEffectRack1_[Channel" + deck + "]]";
};

PioneerDDJ1000.colorFxApply = function(button) {
    var preset = PioneerDDJ1000.COLOR_FX_PRESETS[button];
    PioneerDDJ1000.colorFxSelected = preset ? button : -1;
    var loading = false;
    for (var deck = 1; deck <= 4; deck++) {
        var g = PioneerDDJ1000.quickFxGroup(deck);
        if (preset) {
            if (engine.getValue(g, "loaded_chain_preset") !== preset.index) {
                engine.setValue(g, "loaded_chain_preset", preset.index);
                loading = true;
            }
            engine.setValue(g, "enabled", 1);
        } else {
            engine.setValue(g, "enabled", 0);
        }
    }
    // A freshly loaded preset starts from its stored parameter values; its links only follow
    // super1 once super1 changes. Re-send the knob position after the load has gone through.
    if (loading) {
        engine.beginTimer(150, function() {
            for (var d = 1; d <= 4; d++) { PioneerDDJ1000.colorKnobApply(d, true); }
        }, true);
    } else {
        for (var d2 = 1; d2 <= 4; d2++) { PioneerDDJ1000.colorKnobApply(d2, false); }
    }
};

// COLOR knobs CH1..4: B6 17..1A (MSB) followed by B6 37..3A (LSB), handled here instead of
// a direct super1 mapping so each FX can get Pioneer behaviour (12 o'clock = off).
PioneerDDJ1000.colorKnobMsb = [0, 64, 64, 64, 64];
PioneerDDJ1000.colorKnobValue = [0.5, 0.5, 0.5, 0.5, 0.5];
PioneerDDJ1000.colorKnob = function(channel, control, value, status, group) {
    var deck = (control & 0x1F) - 0x16;
    if (deck < 1 || deck > 4) { return; }
    if (control < 0x20) {
        PioneerDDJ1000.colorKnobMsb[deck] = value;
        return;
    }
    PioneerDDJ1000.colorKnobValue[deck] = (PioneerDDJ1000.colorKnobMsb[deck] * 128 + value) / 16383;
    PioneerDDJ1000.colorKnobApply(deck, false);
};
PioneerDDJ1000.colorKnobApply = function(deck, force) {
    var v = PioneerDDJ1000.colorKnobValue[deck];
    if (Math.abs(v - 0.5) < 0.02) { v = 0.5; }   // detent dead zone
    var preset = PioneerDDJ1000.COLOR_FX_PRESETS[PioneerDDJ1000.colorFxSelected];
    if (preset && preset.bipolar) { v = Math.abs(v - 0.5) * 2; }
    var g = PioneerDDJ1000.quickFxGroup(deck);
    if (force) { engine.setValue(g, "super1", v > 0.5 ? v - 0.001 : v + 0.001); }
    engine.setValue(g, "super1", v);
};

PioneerDDJ1000.colorFxInit = function() {
    print("DDJ-1000 ColorFX: CH1 loaded_chain_preset=" +
        engine.getValue(PioneerDDJ1000.quickFxGroup(1), "loaded_chain_preset") +
        " (expected Filter=" + PioneerDDJ1000.COLOR_FX_PRESETS[PioneerDDJ1000.COLOR_FX_DEFAULT].index + ")");
    PioneerDDJ1000.colorFxApply(PioneerDDJ1000.COLOR_FX_DEFAULT);
    PioneerDDJ1000.colorFxDiagInit();
};

PioneerDDJ1000.colorFxButton = function(channel, control, value, status, group) {
    var noteOn = (status & 0xF0) === 0x90 && value > 0;
    if (noteOn) {
        PioneerDDJ1000.colorFxApply(control);
        engine.beginTimer(500, function() { PioneerDDJ1000.colorFxDump("select " + control); }, true);
    } else if (control === PioneerDDJ1000.colorFxSelected) {
        // Either deselected (lit button pressed again) or replaced; a following note-on re-applies.
        PioneerDDJ1000.colorFxApply(-1);
    }
};

// --- Color FX diagnostics (temporary, 2026-11-08): writes the CH1 QuickEffect state to
// mixxx.log after each selection and when the COLOR knob reaches an end or the center.
PioneerDDJ1000.colorFxDump = function(reason) {
    var g = PioneerDDJ1000.quickFxGroup(1);
    var s = "DDJ-1000 ColorFX dump (" + reason + "): preset=" + engine.getValue(g, "loaded_chain_preset") +
        " enabled=" + engine.getValue(g, "enabled") + " super1=" + engine.getValue(g, "super1").toFixed(3) +
        " mix=" + engine.getValue(g, "mix");
    for (var e = 1; e <= 3; e++) {
        var eg = "[QuickEffectRack1_[Channel1]_Effect" + e + "]";
        if (!engine.getValue(eg, "loaded")) { continue; }
        s += " | E" + e + " on=" + engine.getValue(eg, "enabled") + " meta=" + engine.getValue(eg, "meta").toFixed(3);
        var n = engine.getValue(eg, "num_parameters");
        for (var p = 1; p <= n; p++) {
            s += " p" + p + "=" + engine.getValue(eg, "parameter" + p).toFixed(3);
        }
    }
    print(s);
};
PioneerDDJ1000.colorFxKnobZone = -1;
PioneerDDJ1000.colorFxKnobWatch = function(value) {
    var zone = value < 0.03 ? 0 : (value > 0.97 ? 2 : (Math.abs(value - 0.5) < 0.02 ? 1 : -1));
    if (zone >= 0 && zone !== PioneerDDJ1000.colorFxKnobZone) {
        PioneerDDJ1000.colorFxDump(["knob LOW", "knob CENTER", "knob HIGH"][zone]);
    }
    if (zone >= 0) { PioneerDDJ1000.colorFxKnobZone = zone; }
};
PioneerDDJ1000.colorFxDiagInit = function() {
    engine.makeConnection(PioneerDDJ1000.quickFxGroup(1), "super1", PioneerDDJ1000.colorFxKnobWatch);
};

// ============================================================
// PAD FX1 (ddj1000-linux-driver, 2026-11-08), measured with aseqdump:
// pads 1..8 = 97 10..17 (deck 1); pad status per deck 97/99/9B/9D (note-off 87/89/8B/8D).
// Everything acts only while the pad is held.
//   1-5: effect via [EffectRack1_EffectUnit2], routed to the pad's deck only
//   6: censor (reverse roll)   7: spinback   8: brake
// Chain preset indices: 0-based in Preferences > Effects > chain presets, index 0 = "---".
// ============================================================
PioneerDDJ1000.PAD_STATUS_DECK = {0x97: 1, 0x99: 2, 0x9B: 3, 0x9D: 4};
PioneerDDJ1000.PAD_FX_UNIT = "[EffectRack1_EffectUnit2]";
PioneerDDJ1000.PAD_FX1_EFFECTS = [
    {name: "Reverb", index: 2, super1: 1.0},
    {name: "Echoverb HP", index: 6, super1: 1.0},
    {name: "Sweep (Filter Echo, HPF up)", index: 7, sweepFrom: 0.5, sweepTo: 1.0},
    {name: "White Noise", index: 1, super1: 0.6},
    {name: "Smooth Growl", index: 10, super1: 1.0},
];
PioneerDDJ1000.padFxActive = null;   // {deck, pad, timer}
PioneerDDJ1000.padFxSetSuper = function(v) {
    var u = PioneerDDJ1000.PAD_FX_UNIT;
    // links only follow super1 when it changes, so nudge it once
    engine.setValue(u, "super1", v > 0.5 ? v - 0.001 : v + 0.001);
    engine.setValue(u, "super1", v);
};
PioneerDDJ1000.padFxStop = function() {
    var a = PioneerDDJ1000.padFxActive;
    if (!a) { return; }
    if (a.timer) { engine.stopTimer(a.timer); }
    var u = PioneerDDJ1000.PAD_FX_UNIT;
    engine.setValue(u, "enabled", 0);
    engine.setValue(u, "group_[Channel" + a.deck + "]_enable", 0);
    PioneerDDJ1000.padFxActive = null;
};
PioneerDDJ1000.padFxStart = function(deck, pad) {
    PioneerDDJ1000.padFxStop();
    var fx = PioneerDDJ1000.PAD_FX1_EFFECTS[pad];
    var u = PioneerDDJ1000.PAD_FX_UNIT;
    for (var d = 1; d <= 4; d++) {
        engine.setValue(u, "group_[Channel" + d + "]_enable", d === deck ? 1 : 0);
    }
    engine.setValue(u, "group_[Master]_enable", 0);
    if (engine.getValue(u, "loaded_chain_preset") !== fx.index) {
        engine.setValue(u, "loaded_chain_preset", fx.index);
    }
    engine.setValue(u, "mix", 1);
    engine.setValue(u, "enabled", 1);
    var active = {deck: deck, pad: pad, timer: 0};
    // Diagnostics (temporary, 2026-11-08): Pad FX 1-5 were reported silent
    engine.beginTimer(300, function() {
        print("DDJ-1000 PadFX deck " + deck + " pad " + (pad + 1) + " (" + fx.name + "): preset=" +
            engine.getValue(u, "loaded_chain_preset") + " want=" + fx.index +
            " enabled=" + engine.getValue(u, "enabled") + " mix=" + engine.getValue(u, "mix") +
            " super1=" + engine.getValue(u, "super1").toFixed(2) +
            " route=" + engine.getValue(u, "group_[Channel" + deck + "]_enable") +
            " E1.loaded=" + engine.getValue("[EffectRack1_EffectUnit2_Effect1]", "loaded") +
            " E1.enabled=" + engine.getValue("[EffectRack1_EffectUnit2_Effect1]", "enabled"));
    }, true);
    PioneerDDJ1000.padFxActive = active;
    if (fx.sweepFrom === undefined) {
        // wait for the preset load to go through, then set the knob
        active.timer = engine.beginTimer(80, function() {
            active.timer = 0;
            PioneerDDJ1000.padFxSetSuper(fx.super1);
        }, true);
    } else {
        var v = fx.sweepFrom, step = (fx.sweepTo - fx.sweepFrom) / 60;   // ~2 s sweep
        active.timer = engine.beginTimer(35, function() {
            v = Math.min(fx.sweepTo, v + step);
            engine.setValue(u, "super1", v);
            if (v >= fx.sweepTo && active.timer) { engine.stopTimer(active.timer); active.timer = 0; }
        });
    }
};
PioneerDDJ1000.padFx1 = function(channel, control, value, status, group) {
    var deck = PioneerDDJ1000.PAD_STATUS_DECK[(status & 0x0F) | 0x90];
    if (!deck) { return; }
    var pressed = (status & 0xF0) === 0x90 && value > 0;
    var g = "[Channel" + deck + "]";
    var pad = control - 0x10;
    if (pad < PioneerDDJ1000.PAD_FX1_EFFECTS.length) {
        if (pressed) {
            PioneerDDJ1000.padFxStart(deck, pad);
        } else {
            var a = PioneerDDJ1000.padFxActive;
            if (a && a.deck === deck && a.pad === pad) { PioneerDDJ1000.padFxStop(); }
        }
    } else if (pad === 5) {
        engine.setValue(g, "reverseroll", pressed ? 1 : 0);
    } else if (pad === 6) {
        engine.spinback(deck, pressed);
    } else if (pad === 7) {
        engine.brake(deck, pressed);
    }
};

// PAD FX2 (Shift + PAD FX1): 97 50..57 (deck 1), loop rolls 1/16 .. 8 beats while held.
PioneerDDJ1000.PAD_FX2_ROLLS = ["0.0625", "0.125", "0.25", "0.5", "1", "2", "4", "8"];
PioneerDDJ1000.padFx2 = function(channel, control, value, status, group) {
    var deck = PioneerDDJ1000.PAD_STATUS_DECK[(status & 0x0F) | 0x90];
    var size = PioneerDDJ1000.PAD_FX2_ROLLS[control - 0x50];
    if (!deck || !size) { return; }
    var pressed = (status & 0xF0) === 0x90 && value > 0;
    engine.setValue("[Channel" + deck + "]", "beatlooproll_" + size + "_activate", pressed ? 1 : 0);
};

// Shift + BEAT SYNC (90..93 5C, measured 2026-11-08): toggle this deck as explicit sync leader.
PioneerDDJ1000.syncLeader = function(channel, control, value, status, group) {
    if (value !== 0x7F) { return; }
    engine.setValue(group, "sync_leader", engine.getValue(group, "sync_leader") >= 2 ? 0 : 2);
};

// ============================================================
// Browse (Pioneered skin, 2026-11-08). The skin switches its tabs via [Tab],current
// (0 = Overview, 1 = Browse, 2 = Samples). Library focus via [Library],focused_widget
// (2 = sidebar/folder tree, 3 = track list).
//   VIEW            : Overview <-> Browse
//   BACK            : folder tree <-> track list
//   BROWSE turn     : opens Browse if needed, then scrolls the focused list
//   BROWSE push     : tree: open/close folder (playlist -> its tracks); track list: LOAD
// ============================================================
// Pioneered shows EITHER the track list OR the folder tree, switched by [Sidebar],sidebar_visible.
// browseInit makes that follow the library focus, so whatever has the focus is also visible
// (also when GoToItem on a playlist moves the focus into its tracks).
PioneerDDJ1000.browseInit = function() {
    engine.makeConnection("[Library]", "focused_widget", function(w) {
        if (w === 2 || w === 3) {
            engine.setValue("[Sidebar]", "sidebar_visible", w === 2 ? 1 : 0);
        }
    });
};
PioneerDDJ1000.TAB_OVERVIEW = 0;
PioneerDDJ1000.TAB_BROWSE = 1;
PioneerDDJ1000.showBrowse = function() {
    if (engine.getValue("[Tab]", "current") !== PioneerDDJ1000.TAB_BROWSE) {
        engine.setValue("[Tab]", "current", PioneerDDJ1000.TAB_BROWSE);
        return true;
    }
    return false;
};
PioneerDDJ1000.browseView = function(channel, control, value, status, group) {
    if (value !== 0x7F) { return; }
    var browsing = engine.getValue("[Tab]", "current") === PioneerDDJ1000.TAB_BROWSE;
    engine.setValue("[Tab]", "current", browsing ? PioneerDDJ1000.TAB_OVERVIEW : PioneerDDJ1000.TAB_BROWSE);
};
PioneerDDJ1000.browseBack = function(channel, control, value, status, group) {
    if (value !== 0x7F) { return; }
    PioneerDDJ1000.showBrowse();
    var inTracks = engine.getValue("[Library]", "focused_widget") === 3;
    engine.setValue("[Library]", "focused_widget", inTracks ? 2 : 3);
};
PioneerDDJ1000.browseTurn = function(channel, control, value, status, group) {
    if (PioneerDDJ1000.showBrowse()) { return; }   // first detent only opens Browse
    var w = engine.getValue("[Library]", "focused_widget");
    if (w !== 2 && w !== 3) { engine.setValue("[Library]", "focused_widget", 3); }
    engine.setValue("[Library]", "MoveVertical", value < 64 ? value : value - 128);
};
// BROWSE push = LOAD (96 46..49 = deck 1..4, measured 2026-11-08), rekordbox style:
// in the folder tree it opens/closes the folder (a playlist/crate jumps into its tracks),
// in the track list it loads the selected track onto that deck.
PioneerDDJ1000.browsePush = function(channel, control, value, status, group) {
    if (value !== 0x7F) { return; }
    var deck = control - 0x45;
    if (deck < 1 || deck > 4) { return; }
    if (engine.getValue("[Tab]", "current") === PioneerDDJ1000.TAB_BROWSE &&
            engine.getValue("[Library]", "focused_widget") === 2) {
        engine.setValue("[Library]", "GoToItem", 1);
        return;
    }
    engine.setValue("[Channel" + deck + "]", "LoadSelectedTrack", 1);
};
