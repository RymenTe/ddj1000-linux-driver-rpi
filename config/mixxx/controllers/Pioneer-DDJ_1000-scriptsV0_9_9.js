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

		// ------ Cue marker, key, sync on jog (2026-11-09)
		PioneerDDJ1000.JogDisplayConnect();
		
		// ------ Deck state for the bridge / HID jog displays (2026-11-09)
		PioneerDDJ1000.bridgeStateStart();

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
		if (PioneerDDJ1000.bridgeMode) { return; } // 2026-11-09: jog display via bridge/HID, MIDI ignored by the DDJ
		
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
		
		// 2026-11-09: full time instead of seconds%60 (avoided a 180° jump every minute)
		PioneerDDJ1000.CurrentPositionBarUpdate(channel,actualTime);
	};

	// 2026-11-09: angle on the jog ring for a track time in seconds (0..359)
	PioneerDDJ1000.jogAngle = function (seconds) {
		return Math.floor(seconds*9*positionBarSpeedFactor) % 360;
	};

	PioneerDDJ1000.CurrentPositionBarUpdate = function (channelNumber,value){ // David Goodenough
		var channelNbrCode = 176+(channelNumber-1);
		var valueOnA360Circle = PioneerDDJ1000.jogAngle(value);
		var MSB = Math.floor(valueOnA360Circle/128);
		var LSB = valueOnA360Circle - (128*MSB);

		midi.sendShortMsg(channelNbrCode,0x14,MSB);
		midi.sendShortMsg(channelNbrCode,0x34,LSB);

	};

	// ----- 2026-11-09: further jog display info (DDJ-1000RB MIDI Messages, p. 8)

	// Cue marker Bn 17/37: angle of the main cue point, 0x7F/0x7F hides it
	PioneerDDJ1000.CueMarkerDisplay = function (value, group) {
		var channel = script.deckFromGroup(group);
		var port = 0xB0 + (channel-1);
		var cue = engine.getValue(group, "cue_point");
		var samples = engine.getValue(group, "track_samples");
		var duration = engine.getValue(group, "duration");
		if (cue < 0 || samples <= 0 || duration <= 0) {
			midi.sendShortMsg(port,0x17,0x7F);
			midi.sendShortMsg(port,0x37,0x7F);
			return;
		}
		var angle = PioneerDDJ1000.jogAngle(cue / samples * duration);
		midi.sendShortMsg(port,0x17,Math.floor(angle/128));
		midi.sendShortMsg(port,0x37,angle%128);
	};

	// Key 9n 49: Mixxx key 1-12 = C..B major, 13-24 = C..B minor (0 = none)
	// DDJ: 0 = "---", 1 = C, 2 = Am, 3 = Db, 4 = Bbm ... (major + relative minor, ascending)
	PioneerDDJ1000.KeyDisplay = function (value, group) {
		var channel = script.deckFromGroup(group);
		var key = Math.round(engine.getValue(group, "key"));
		var code = 0;
		if (key >= 1 && key <= 12) {
			code = 1 + 2*(key-1);
		} else if (key >= 13 && key <= 24) {
			code = 2 + 2*(((key-13)+3) % 12);
		}
		midi.sendShortMsg(0x90+(channel-1),0x49,code);
		// Key variation 9n 4A: 0x0D = 0, +-12 semitones
		var shift = Math.round(engine.getValue(group, "pitch_adjust"));
		shift = Math.max(-12, Math.min(12, shift));
		midi.sendShortMsg(0x90+(channel-1),0x4A,0x0D+shift);
	};

	// Beat Sync Master 9n 59 / Beat Sync State 9n 5A
	PioneerDDJ1000.SyncDisplay = function (value, group) {
		var channel = script.deckFromGroup(group);
		midi.sendShortMsg(0x90+(channel-1),0x59,engine.getValue(group, "sync_leader") > 0 ? 0x7F : 0x00);
		midi.sendShortMsg(0x90+(channel-1),0x5A,engine.getValue(group, "sync_enabled") > 0 ? 0x7F : 0x00);
	};

	PioneerDDJ1000.JogDisplayConnect = function () {
		var controls = {
			"cue_point": PioneerDDJ1000.CueMarkerDisplay,
			"track_samples": PioneerDDJ1000.CueMarkerDisplay,
			"key": PioneerDDJ1000.KeyDisplay,
			"pitch_adjust": PioneerDDJ1000.KeyDisplay,
			"sync_leader": PioneerDDJ1000.SyncDisplay,
			"sync_enabled": PioneerDDJ1000.SyncDisplay
		};
		for (var d = 1; d <= 4; d++) {
			var group = "[Channel" + d + "]";
			for (var co in controls) {
				engine.makeConnection(group, co, controls[co]).trigger();
			}
		}
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
		if (PioneerDDJ1000.bridgeMode) { return; } // 2026-11-09: jog display via bridge/HID
		
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
		
		// Playing speed Bn 16/36: 1000 = 0.0 %, steps of 0.1 % (0 = -100 %, 2000 = +100 %)
		// 2026-11-09: computed from bpm/file_bpm (independent of the pitch fader direction);
		// before, negative speeds were sent like positive ones (1000 - negative).
		var fileBpm = engine.getValue(group, "file_bpm");
		if (fileBpm > 0 && value > 0) {
			absolutePitchRange = Math.round((value / fileBpm - 1) * 1000);
		}
		absolutePitchRange = Math.max(-1000, Math.min(1000, absolutePitchRange));
		adaptPitchRange = 1000 + absolutePitchRange;
		MSB = Math.floor(adaptPitchRange / 128);
		LSB = adaptPitchRange % 128;

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
		
		// 2026-11-08: generic (group), used by all four decks
		var isLoopEnabled = engine.getValue(group,"loop_enabled");
		
		if (value == 0x7F) {
		
			if (isLoopEnabled) {	// If Loop is already set
				engine.setValue(group,"loop_halve",1);
			} else {
				engine.setValue(group,"loop_in",1);
			}
		
		}
		
	};
	
	PioneerDDJ1000.LoopScaleMultiplyPer2CH1 = function (channel, control, value, status, group) {
	
		var isLoopEnabled = engine.getValue(group,"loop_enabled");
		//var actualLoopScale = engine.getValue("[Channel1]","loop_scale");
		
		if (value == 0x7F) {
		
			if (isLoopEnabled) {	// If Loop is already set
				engine.setValue(group,"loop_double",1);
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

// Beat FX type list (2026-11-08): own chain presets with FIXED values (see PAD FX1); stepping
// through all Mixxx effects landed on EQs/Autopan/Metronome, which are inaudible on one deck.
// LEVEL/DEPTH = unit mix (XML). Index = position in effects.xml <ChainPresetList> + 1.
PioneerDDJ1000.BEAT_FX_LIST = [
    {name: "ECHO 1/2", index: 13},
    {name: "ECHO 1/4", index: 12},
    {name: "ECHO 1/2 LONG", index: 14},
    {name: "REVERB", index: 15},
    {name: "FLANGER", index: 16},
    {name: "FILTER (HPF)", index: 17},
];
PioneerDDJ1000.beatFxPos = 0;
PioneerDDJ1000.beatFxOn = false;
PioneerDDJ1000.beatFxApplyOn = function() {
    for (var e = 1; e <= 3; e++) {
        var g = "[EffectRack1_EffectUnit1_Effect" + e + "]";
        if (engine.getValue(g, "loaded")) { engine.setValue(g, "enabled", PioneerDDJ1000.beatFxOn ? 1 : 0); }
    }
};
PioneerDDJ1000.beatFxLoad = function() {
    var fx = PioneerDDJ1000.BEAT_FX_LIST[PioneerDDJ1000.beatFxPos];
    engine.setValue(PioneerDDJ1000.BEAT_FX_UNIT, "enabled", 1);
    engine.setValue(PioneerDDJ1000.BEAT_FX_UNIT, "loaded_chain_preset", fx.index);
    PioneerDDJ1000.beatFxApplyOn();
    engine.beginTimer(60, PioneerDDJ1000.beatFxApplyOn, true);   // preset load may reset slot flags
    print("DDJ-1000 BeatFX type " + fx.name + " (preset " + fx.index + ") on=" + PioneerDDJ1000.beatFxOn);
};

PioneerDDJ1000.beatFxOnOff = function(channel, control, value, status, group) {
    if (value !== 0x7F) {
        return;
    }
    if (engine.getValue(PioneerDDJ1000.BEAT_FX_UNIT, "loaded_chain_preset") !==
        PioneerDDJ1000.BEAT_FX_LIST[PioneerDDJ1000.beatFxPos].index) {
        PioneerDDJ1000.beatFxLoad();
    }
    PioneerDDJ1000.beatFxOn = !PioneerDDJ1000.beatFxOn;
    var on = PioneerDDJ1000.beatFxOn;
    PioneerDDJ1000.beatFxApplyOn();
    midi.sendShortMsg(0x94, 0x47, on ? 0x7F : 0x00);
    // Diagnostics (temporary, 2026-11-08): which channel gets the FX when it is switched on
    var u = PioneerDDJ1000.BEAT_FX_UNIT, st = "DDJ-1000 BeatFX ON/OFF -> on=" + (on ? 1 : 0) +
        " type=" + PioneerDDJ1000.BEAT_FX_LIST[PioneerDDJ1000.beatFxPos].name + " route:";
    ["[Channel1]", "[Channel2]", "[Channel3]", "[Channel4]", "[Master]"].forEach(function(g) {
        if (engine.getValue(u, "group_" + g + "_enable")) { st += " " + g; }
    });
    st += " mix=" + engine.getValue(u, "mix").toFixed(2) + " E1.enabled=" +
        engine.getValue(PioneerDDJ1000.BEAT_FX_EFFECT, "enabled");
    for (var d = 1; d <= 4; d++) {
        st += " D" + d + ".play=" + engine.getValue("[Channel" + d + "]", "play") +
            " vol=" + engine.getValue("[Channel" + d + "]", "volume").toFixed(2);
    }
    print(st);
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
    var n = PioneerDDJ1000.BEAT_FX_LIST.length;
    if (step === 1) {
        PioneerDDJ1000.beatFxPos = (PioneerDDJ1000.beatFxPos + 1) % n;
    } else if (step === 2) {
        PioneerDDJ1000.beatFxPos = (PioneerDDJ1000.beatFxPos + n - 1) % n;
    } else {
        return;
    }
    PioneerDDJ1000.beatFxLoad();
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
    // Beat FX: handled by the DDJ-1000's own DSP (LOW CUT ECHO etc. on the unit display);
    // no Mixxx mapping since 2026-11-08 (Mixxx only sends the master mix, so the built-in
    // Beat FX work on MST only). The beatFx* functions below are kept but unused.
    // Clear what the earlier software Beat FX left in Effect Unit 1 (state is persisted).
    for (var e = 1; e <= 3; e++) {
        engine.setValue("[EffectRack1_EffectUnit1_Effect" + e + "]", "enabled", 0);
    }
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
// Layout = rekordbox default PAD FX1 bank (screenshot 2026-11-08):
//   1 ROLL 1/2   2 SWEEP   3 FLANGER 16   4 V.BRAKE 3/4
//   5 ECHO 1/4   6 ECHO 1/2   7 REVERB 50   8 ECHO 1/2 (longer tail)
// Effects use own chain presets "PadFX ..." with FIXED values (no super1/meta links: links did
// not move the parameters -> reverb stayed at send 0, noise at full). Index = position in
// effects.xml <ChainPresetList> + 1 ("---" is 0).
PioneerDDJ1000.PAD_FX1_EFFECTS = [
    {name: "Roll 1/2", roll: "0.5"},
    {name: "Sweep", index: 17},
    {name: "Flanger 16", index: 16},
    {name: "V.Brake 3/4", brakeBeats: 0.75},
    {name: "Echo 1/4", index: 12},
    {name: "Echo 1/2", index: 13},
    {name: "Reverb 50", index: 15},
    {name: "Echo 1/2 long", index: 14},
];
PioneerDDJ1000.padFxActive = null;   // {deck, pad, timer}
PioneerDDJ1000.padFxSetSuper = function(v) {
    var u = PioneerDDJ1000.PAD_FX_UNIT;
    engine.setValue(u, "super1", v);
    // The effects' meta knobs use soft takeover: a jump of super1 away from the preset's
    // stored meta value (e.g. 0 -> 1) is ignored, so the linked parameters never move.
    // Set each loaded effect's meta directly.
    for (var e = 1; e <= 3; e++) {
        var g = u.replace("]", "_Effect" + e + "]");
        if (engine.getValue(g, "loaded")) { engine.setValue(g, "meta", v); }
    }
};
PioneerDDJ1000.padFxEnableSlots = function() {
    for (var e = 1; e <= 3; e++) {
        var g = "[EffectRack1_EffectUnit2_Effect" + e + "]";
        if (engine.getValue(g, "loaded")) { engine.setValue(g, "enabled", 1); }
    }
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
    // The slots' own enabled flags are kept per unit (not per preset) and were 0 -> silence.
    PioneerDDJ1000.padFxEnableSlots();
    engine.beginTimer(60, PioneerDDJ1000.padFxEnableSlots, true);
    var active = {deck: deck, pad: pad, timer: 0};
    // Diagnostics (temporary, 2026-11-08): Pad FX 1-5 were reported silent
    engine.beginTimer(300, function() {
        print("DDJ-1000 PadFX deck " + deck + " pad " + (pad + 1) + " (" + fx.name + "): preset=" +
            engine.getValue(u, "loaded_chain_preset") + " want=" + fx.index +
            " enabled=" + engine.getValue(u, "enabled") + " mix=" + engine.getValue(u, "mix") +
            " super1=" + engine.getValue(u, "super1").toFixed(2) +
            " route=" + engine.getValue(u, "group_[Channel" + deck + "]_enable") +
            " E1.loaded=" + engine.getValue("[EffectRack1_EffectUnit2_Effect1]", "loaded") +
            " E1.enabled=" + engine.getValue("[EffectRack1_EffectUnit2_Effect1]", "enabled") +
            " meta=" + [1, 2, 3].map(function(e) {
                return engine.getValue("[EffectRack1_EffectUnit2_Effect" + e + "]", "meta").toFixed(2);
            }).join("/"));
    }, true);
    PioneerDDJ1000.padFxActive = active;
};
PioneerDDJ1000.padFx1 = function(channel, control, value, status, group) {
    var deck = PioneerDDJ1000.PAD_STATUS_DECK[(status & 0x0F) | 0x90];
    if (!deck) { return; }
    var pressed = (status & 0xF0) === 0x90 && value > 0;
    var g = "[Channel" + deck + "]";
    var pad = control - 0x10;
    var fx = PioneerDDJ1000.PAD_FX1_EFFECTS[pad];
    if (!fx) { return; }
    if (fx.roll) {
        engine.setValue(g, "beatlooproll_" + fx.roll + "_activate", pressed ? 1 : 0);
    } else if (fx.brakeBeats) {
        if (pressed) {
            // stop within ~3/4 beat; engine.brake factor 1 ~ 1 s to standstill (tune by ear)
            var bpm = engine.getValue(g, "bpm") || 120;
            var seconds = fx.brakeBeats * 60 / bpm;
            engine.brake(deck, true, Math.max(0.3, 1 / seconds));
        } else {
            engine.brake(deck, false);
        }
    } else if (pressed) {
        PioneerDDJ1000.padFxStart(deck, pad);
    } else {
        var a = PioneerDDJ1000.padFxActive;
        if (a && a.deck === deck && a.pad === pad) { PioneerDDJ1000.padFxStop(); }
    }
};

// 4 BEAT LOOP button (9x 14), 2026-11-08: if any loop is active (also a manual IN/OUT loop
// or another size) the button exits it; only without a loop it sets a 4-beat loop.
PioneerDDJ1000.beatLoop4OrExit = function(channel, control, value, status, group) {
    if (value !== 0x7F) { return; }
    if (engine.getValue(group, "loop_enabled")) {
        engine.setValue(group, "reloop_toggle", 1);
    } else {
        engine.setValue(group, "beatloop_4_activate", 1);
    }
};

// BEAT LOOP (Shift + BEAT JUMP pad mode), 2026-11-08 – note numbers ASSUMED by analogy to
// PAD FX2 (= PAD FX1 + 0x40): 97/99/9B/9D 60..67. Pressing toggles a beat loop of that size.
PioneerDDJ1000.BEAT_LOOP_SIZES = ["0.25", "0.5", "1", "2", "4", "8", "16", "32"];
PioneerDDJ1000.beatLoopPad = function(channel, control, value, status, group) {
    var deck = PioneerDDJ1000.PAD_STATUS_DECK[(status & 0x0F) | 0x90];
    var size = PioneerDDJ1000.BEAT_LOOP_SIZES[control - 0x60];
    print("DDJ-1000 BeatLoop status=0x" + status.toString(16) + " note=0x" + control.toString(16) +
        " value=" + value + " deck=" + deck + " size=" + size);
    if (!deck || !size || (status & 0xF0) !== 0x90 || value === 0) { return; }
    engine.setValue("[Channel" + deck + "]", "beatloop_" + size + "_toggle", 1);
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

// 2026-11-09: CROSSFADER ASSIGN switches (DDJ-1000RB MIDI Messages: 9n 16 = A, 9n 1D = THRU, 9n 18 = B).
// The DDJ sends the new position with 0x7F (also in the status dump when the mapping loads).
// Mixxx orientation: 0 = left (A), 1 = center (THRU), 2 = right (B).
PioneerDDJ1000.crossfaderAssign = function(channel, control, value, status, group) {
    if (value !== 0x7F) {
        return;
    }
    var orientation = {0x16: 0, 0x1D: 1, 0x18: 2}[control];
    if (orientation === undefined) {
        return;
    }
    engine.setValue(group, "orientation", orientation);
    print("DDJ-1000 XfaderAssign: " + group + " note 0x" + control.toString(16) + " -> orientation " + orientation);
};

// true when running behind scripts/runtime/ddj1000-bridge.py (heartbeat session): the DDJ ignores the
// MIDI jog display messages then, so the high-rate ones (time/position, BPM/tempo) are not sent.
PioneerDDJ1000.bridgeMode = true;

// 2026-11-09: deck state for the DDJ-1000 bridge (scripts/runtime/ddj1000-bridge.py), which drives the
// jog displays via HID. One SysEx per deck every 50 ms; the bridge consumes it (never reaches the DDJ):
// F0 7D 44 42 01 deck flags pos:4 len:4 filebpm*100:3 bpm*100:3 tempo*100+2^20:3 key shift+12 firstbeat:3 F7
PioneerDDJ1000.bridgeEnc = function(out, value, n) {
    value = Math.max(0, Math.round(value));
    for (var i = 0; i < n; i++) {
        out.push(value % 128);
        value = Math.floor(value / 128);
    }
};

PioneerDDJ1000.bridgeSendState = function() {
    for (var d = 1; d <= 4; d++) {
        var g = "[Channel" + d + "]";
        var loaded = engine.getValue(g, "track_loaded") > 0;
        var duration = engine.getValue(g, "duration");
        var fileBpm = engine.getValue(g, "file_bpm");
        var bpm = engine.getValue(g, "bpm");
        var tempo = fileBpm > 0 ? (bpm / fileBpm - 1) * 100 : 0;
        var firstBeat = 0;
        var closest = engine.getValue(g, "beat_closest");
        var rate = engine.getValue(g, "track_samplerate");
        if (fileBpm > 0 && closest >= 0 && rate > 0) {
            var beatMs = 60000 / fileBpm;
            firstBeat = ((closest / (rate * 2)) * 1000) % beatMs;
        }
        var flags = (loaded ? 1 : 0) | (engine.getValue(g, "play") > 0 ? 2 : 0) |
                    (engine.getValue(g, "sync_leader") > 0 ? 4 : 0) |
                    (engine.getValue(g, "sync_enabled") > 0 ? 8 : 0);
        var shift = Math.max(-12, Math.min(12, Math.round(engine.getValue(g, "pitch_adjust"))));
        var msg = [0xF0, 0x7D, 0x44, 0x42, 0x01, d - 1, flags];
        PioneerDDJ1000.bridgeEnc(msg, engine.getValue(g, "playposition") * duration * 1000, 4);
        PioneerDDJ1000.bridgeEnc(msg, duration * 1000, 4);
        PioneerDDJ1000.bridgeEnc(msg, fileBpm * 100, 3);
        PioneerDDJ1000.bridgeEnc(msg, bpm * 100, 3);
        PioneerDDJ1000.bridgeEnc(msg, tempo * 100 + 1048576, 3);
        msg.push(Math.max(0, Math.min(24, Math.round(engine.getValue(g, "key")))));
        msg.push(shift + 12);
        PioneerDDJ1000.bridgeEnc(msg, firstBeat, 3);
        msg.push(0xF7);
        midi.sendSysexMsg(msg, msg.length);
    }
    PioneerDDJ1000.bridgeSendCues();
};

// 2026-11-09: hot cues 1-8 per deck for the jog displays (bridge sends HID 30 01/30 02), only on change
// and every 2 s as a refresh: F0 7D 44 42 02 deck { status type pos_ms:4 rgb:4 } x8 loopflags start_ms:4 end_ms:4 F7
// status 0 = none, type = Mixxx hotcue_X_type (1 hot cue, 4 loop); loopflags bit0 start set, bit1 end set, bit2 enabled.
PioneerDDJ1000.bridgeCueCache = ["", "", "", ""];
PioneerDDJ1000.bridgeCueTick = 0;

PioneerDDJ1000.bridgeSendCues = function() {
    var refresh = (++PioneerDDJ1000.bridgeCueTick % 40) === 0;
    for (var d = 1; d <= 4; d++) {
        var g = "[Channel" + d + "]";
        var rate = engine.getValue(g, "track_samplerate");
        var msg = [0xF0, 0x7D, 0x44, 0x42, 0x02, d - 1];
        for (var i = 1; i <= 8; i++) {
            var status = engine.getValue(g, "hotcue_" + i + "_status");
            var pos = engine.getValue(g, "hotcue_" + i + "_position");
            var set = status > 0 && pos >= 0 && rate > 0;
            msg.push(set ? 1 : 0);
            msg.push(set ? Math.max(0, Math.min(127, engine.getValue(g, "hotcue_" + i + "_type"))) : 0);
            PioneerDDJ1000.bridgeEnc(msg, set ? pos / (rate * 2) * 1000 : 0, 4);
            PioneerDDJ1000.bridgeEnc(msg, set ? engine.getValue(g, "hotcue_" + i + "_color") : 0, 4);
        }
        var ls = engine.getValue(g, "loop_start_position");
        var le = engine.getValue(g, "loop_end_position");
        var lsSet = ls >= 0 && rate > 0;
        var leSet = le >= 0 && rate > 0;
        msg.push((lsSet ? 1 : 0) | (leSet ? 2 : 0) | (engine.getValue(g, "loop_enabled") > 0 ? 4 : 0));
        PioneerDDJ1000.bridgeEnc(msg, lsSet ? ls / (rate * 2) * 1000 : 0, 4);
        PioneerDDJ1000.bridgeEnc(msg, leSet ? le / (rate * 2) * 1000 : 0, 4);
        msg.push(0xF7);
        var key = msg.join(",");
        if (refresh || key !== PioneerDDJ1000.bridgeCueCache[d - 1]) {
            PioneerDDJ1000.bridgeCueCache[d - 1] = key;
            midi.sendSysexMsg(msg, msg.length);
        }
    }
};

PioneerDDJ1000.bridgeStateStart = function() {
    if (PioneerDDJ1000.bridgeStateTimer) {
        engine.stopTimer(PioneerDDJ1000.bridgeStateTimer);
    }
    PioneerDDJ1000.bridgeStateTimer = engine.beginTimer(50, PioneerDDJ1000.bridgeSendState);
};

// ---------------------------------------------------------------------------------------------------------------
// 2026-11-09: hot-cue pads light up in the Mixxx hot-cue colour. The DDJ colour code is a hue-wheel index
// (01 blue ... 16 green, 1E yellow, 24 orange, 2A red, 30 pink, 3C lavender), measured on the jog display;
// same table as cue_colour() in scripts/runtime/ddj1000_display.py. Replaces the fixed HC_Color and fixes
// deck 4 hot-cue LEDs (were sent to the deck 3 pads).
// ---------------------------------------------------------------------------------------------------------------
PioneerDDJ1000.cueHueAnchors = [[230, 0x01], [175, 0x0C], [160, 0x12], [120, 0x16], [85, 0x1A], [60, 0x1E],
                                [35, 0x24], [0, 0x2A], [-30, 0x30], [-45, 0x36], [-80, 0x3C]];
PioneerDDJ1000.cueColourDefault = 0x16;

PioneerDDJ1000.cueColourCode = function(rgb) {
    if (rgb === undefined || rgb < 0) {
        return PioneerDDJ1000.cueColourDefault;
    }
    var r = ((rgb >> 16) & 0xFF) / 255, g = ((rgb >> 8) & 0xFF) / 255, b = (rgb & 0xFF) / 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
    if (max < 0.1 || delta / max < 0.15) {
        return PioneerDDJ1000.cueColourDefault;
    }
    var hue;
    if (max === r) {
        hue = 60 * (((g - b) / delta) % 6);
    } else if (max === g) {
        hue = 60 * ((b - r) / delta + 2);
    } else {
        hue = 60 * ((r - g) / delta + 4);
    }
    if (hue < 0) { hue += 360; }
    if (hue > 230) {
        hue -= 360;
        if (hue < -80) { return hue < -105 ? 0x01 : 0x3C; }
    }
    var a = PioneerDDJ1000.cueHueAnchors;
    for (var i = 0; i + 1 < a.length; i++) {
        if (hue <= a[i][0] && hue >= a[i + 1][0]) {
            return Math.round(a[i][1] + (a[i + 1][1] - a[i][1]) * (a[i][0] - hue) / (a[i][0] - a[i + 1][0]));
        }
    }
    return 0x01;
};

PioneerDDJ1000.hotcuePadPorts = [HcCH1Port, HcCH2Port, HcCH3Port, HcCH4Port];

PioneerDDJ1000.hotcuePadColour = function(deck, n) {
    var g = "[Channel" + deck + "]";
    if (engine.getValue(g, "hotcue_" + n + "_status") <= 0) {
        return Black;
    }
    return PioneerDDJ1000.cueColourCode(engine.getValue(g, "hotcue_" + n + "_color"));
};

PioneerDDJ1000.hotcueLed = function(deck, n) {
    var port = PioneerDDJ1000.hotcuePadPorts[deck - 1];
    var c = PioneerDDJ1000.hotcuePadColour(deck, n);
    midi.sendShortMsg(port, n - 1, c);
    midi.sendShortMsg(port + 1, n - 1, c); // shift page
};

(function() {
    for (var d = 1; d <= 4; d++) {
        for (var n = 1; n <= 8; n++) {
            PioneerDDJ1000["HotCue" + n + "TriggerCH" + d] = (function(deck, num) {
                return function() { PioneerDDJ1000.hotcueLed(deck, num); };
            })(d, n);
        }
    }
})();

PioneerDDJ1000.hotcueTriggerInitOrig = PioneerDDJ1000.HotCueTriggerInit;
PioneerDDJ1000.HotCueTriggerInit = function() {
    PioneerDDJ1000.hotcueTriggerInitOrig();
    PioneerDDJ1000.hotcueColourConns = [];
    for (var d = 1; d <= 4; d++) {
        for (var n = 1; n <= 8; n++) {
            PioneerDDJ1000.hotcueColourConns.push(engine.makeConnection("[Channel" + d + "]", "hotcue_" + n + "_color",
                (function(deck, num) { return function() { PioneerDDJ1000.hotcueLed(deck, num); }; })(d, n)));
            PioneerDDJ1000.hotcueLed(d, n);
        }
    }
};

// press dims the pad (as before), release restores the hot-cue colour instead of the fixed HC_Color
PioneerDDJ1000.HotCueTouch = function(channel, control, value, status, group) {
    var n = control + 1;
    if (control > 7 || engine.getValue(group, "hotcue_" + n + "_status") <= 0) {
        return;
    }
    var port = 0x90 | (status & 0x0F); // the DDJ sends real note-offs (8x) on release
    if (value === 0x7F && (status & 0xF0) === 0x90) {
        midi.sendShortMsg(port, control, HC_dimmedColor);
    } else {
        var deck = parseInt(group.substring(8, 9), 10);
        midi.sendShortMsg(port, control, PioneerDDJ1000.hotcuePadColour(deck, n));
    }
};
