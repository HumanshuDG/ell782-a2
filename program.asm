; =====================================================================
;  program.asm  -  WM-8 washing-machine control program
;  ELL7282/ELL782 Assignment 2  (5-stage pipelined 8-bit microcontroller)
;
;  Encoding:  R  op[15:12] ra[11:9] rb[8:6] 000000
;             I  op[15:12] ra[11:9] 0 imm8[7:0]
;             N  op[15:12] 000000000000
;  Custom:    SGEU Rd,Rs   Rd <- (Rd >= Rs, unsigned) ? 1 : 0     (opcode C)
;
;  Mode parameters (MODE[0] selects; MODE[1] is ignored):
;     MODE[0]=0  NORMAL : fill target 100, wash 64 ticks, spin 32 ticks
;     MODE[0]=1  HEAVY  : fill target 160, wash 96 ticks, spin 48 ticks
;     both modes        : drain threshold 10 (WATER_LEVEL <= 10)
;
;  DISPLAY codes: 01 idle | m2 lock+check | m3 fill | m4 wash | m5 drain
;                 m6 spin | m7 stopping  | m8 done   (m = 0 NORMAL, 4 HEAVY,
;                 high nibble = MODE<<2)   E1 door-open abort, EE safety trip
; =====================================================================

; ---- peripheral addresses (memory_map.pdf) ----
        .equ IN_STATUS,   0xF0   ; R : b0 START b1 DOOR_CLOSED b3:2 MODE b4 TRIP b5 MOTOR_ACTUAL
        .equ WATER_LEVEL, 0xF1   ; R
        .equ TEMP,        0xF2   ; R
        .equ DRUM_RPM,    0xF3   ; R
        .equ ACT,         0xF4   ; RW: b0 VALVE b1 HEATER b2 MOTOR_EN b3 PUMP b4 DIR b5 LOCK b6 BUZZER
        .equ DISPLAY,     0xF5   ; RW
        .equ T_COUNT,     0xF8   ; R
        .equ T_LIMIT,     0xF9   ; RW
        .equ T_CTRL,      0xFA   ; RW: b0 EN, b1 CLR (write-1 command, reads 0)
        .equ T_STATUS,    0xFB   ; R : b0 MATCH (sticky)
; ---- RAM variables ----
        .equ V_TARGET,    0x00
        .equ V_WASH,      0x01
        .equ V_SPIN,      0x02
        .equ V_DRAIN,     0x03
        .equ V_TAG,       0x04   ; MODE<<4 snapshot (display tag)
        .equ V_TEMP,      0x05   ; temperature logged at wash start
; ---- actuator patterns ----
        .equ A_OFF,       0x00
        .equ A_LOCK,      0x20
        .equ A_FILL,      0x21   ; LOCK | VALVE_IN
        .equ A_WASH,      0x24   ; LOCK | MOTOR_EN   (+0x10 MOTOR_DIR)
        .equ A_DRAIN,     0x28   ; LOCK | PUMP_OUT
        .equ A_SPIN,      0x2C   ; LOCK | PUMP_OUT | MOTOR_EN
        .equ A_DONE,      0x40   ; BUZZER, door unlocked

reset:  LDI  R0, A_OFF
        LDI  R7, ACT
        ST   R0, [R7]           ; all actuator requests off, door unlocked
        LDI  R7, T_CTRL
        LDI  R1, 0x02
        ST   R1, [R7]           ; timer: clear, disabled
idle:   LDI  R7, DISPLAY
        LDI  R1, 0x01
        ST   R1, [R7]           ; DISPLAY = 01 (ready)
idle_wait:
        LDI  R7, IN_STATUS
wait_start:
        LD   R1, [R7]           ; one status snapshot
        LDI  R2, 0x03
        AND  R2, R1             ; START & DOOR_CLOSED bits
        ADDI R2, -3             ; 0 only if START=1 and DOOR_CLOSED=1
        BNEZ R2, wait_start
; ---------------- START accepted: latch MODE from the same snapshot ----
        LDI  R3, 0x0C
        AND  R3, R1             ; MODE<<2
        ADD  R3, R3
        ADD  R3, R3             ; MODE<<4  = display tag
        LDI  R7, V_TAG
        ST   R3, [R7]           ; RAM[4] = tag (MODE snapshot)
        LDI  R2, 0x04
        AND  R2, R1             ; MODE[0]
        BNEZ R2, heavy
        LDI  R4, 100            ; NORMAL: fill target
        LDI  R5, 64             ;         wash ticks
        LDI  R6, 32             ;         spin ticks
        JMP  save
heavy:  LDI  R4, 160            ; HEAVY : fill target
        LDI  R5, 96             ;         wash ticks
        LDI  R6, 48             ;         spin ticks
save:   LDI  R7, V_TARGET
        ST   R4, [R7]           ; RAM[0] = target
        ADDI R7, 1
        ST   R5, [R7]           ; RAM[1] = wash
        ADDI R7, 1
        ST   R6, [R7]           ; RAM[2] = spin
        ADDI R7, 1
        LDI  R4, 10
        ST   R4, [R7]           ; RAM[3] = drain threshold
; ---------------- lock door, then re-check the door sensor --------------
        LDI  R6, ACT            ; R6 = actuator latch pointer (kept)
        LDI  R1, A_LOCK
        ST   R1, [R6]
        LDI  R7, DISPLAY
        MOV  R1, R3
        ADDI R1, 0x02
        ST   R1, [R7]           ; DISPLAY = tag|2
        LDI  R7, IN_STATUS
        LD   R1, [R7]
        LDI  R2, 0x02
        AND  R2, R1
        BEQZ R2, door_abort     ; lock request does not prove the door is shut
; ---------------- FILL until WATER_LEVEL >= target (unsigned) -----------
        LDI  R1, A_FILL
        ST   R1, [R6]
        LDI  R7, DISPLAY
        MOV  R1, R3
        ADDI R1, 0x03
        ST   R1, [R7]           ; DISPLAY = tag|3
        LDI  R7, V_TARGET
        LD   R4, [R7]           ; R4 = target
        LDI  R7, WATER_LEVEL
fill:   LD   R1, [R7]
        SGEU R1, R4             ; R1 = (WATER_LEVEL >= target)
        BEQZ R1, fill
        LDI  R1, A_LOCK
        ST   R1, [R6]           ; close valve
; ---------------- WASH: timer interval 1, alternate direction ------------
        LDI  R7, DISPLAY
        MOV  R1, R3
        ADDI R1, 0x04
        ST   R1, [R7]           ; DISPLAY = tag|4
        LDI  R7, TEMP
        LD   R1, [R7]
        LDI  R7, V_TEMP
        ST   R1, [R7]           ; log temperature (sensor read-back only)
        LDI  R7, V_WASH
        LD   R5, [R7]
        LDI  R7, T_LIMIT
        ST   R5, [R7]           ; LIMIT = wash ticks
        LDI  R7, T_CTRL
        LDI  R1, 0x03
        ST   R1, [R7]           ; clear COUNT/MATCH and enable
        LDI  R0, IN_STATUS
        LDI  R2, 0x10           ; COUNT bit4 -> MOTOR_DIR (toggles every 16 ticks)
        LDI  R3, A_WASH
        LDI  R4, 0x10           ; TRIP bit mask
        LDI  R5, T_COUNT
        LDI  R7, T_STATUS
wash:   LD   R1, [R5]
        AND  R1, R2
        ADD  R1, R3             ; LOCK | MOTOR_EN | DIR
        ST   R1, [R6]
        LD   R1, [R0]
        AND  R1, R4
        BNEZ R1, trip_fault     ; hardware interlock tripped
        LD   R1, [R7]
        BEQZ R1, wash           ; until MATCH
        LDI  R1, A_LOCK
        ST   R1, [R6]           ; stop motor
; ---------------- DRAIN until WATER_LEVEL <= threshold (unsigned) --------
        LDI  R1, A_DRAIN
        ST   R1, [R6]
        LDI  R7, V_TAG
        LD   R1, [R7]
        ADDI R1, 0x05
        LDI  R7, DISPLAY
        ST   R1, [R7]           ; DISPLAY = tag|5
        LDI  R7, V_DRAIN
        LD   R4, [R7]           ; R4 = threshold
        LDI  R7, WATER_LEVEL
drain:  LD   R1, [R7]
        MOV  R2, R4
        SGEU R2, R1             ; R2 = (threshold >= WATER_LEVEL)
        BEQZ R2, drain
; ---------------- SPIN: clear / re-arm timer for interval 2 --------------
        LDI  R7, V_TAG
        LD   R1, [R7]
        ADDI R1, 0x06
        LDI  R7, DISPLAY
        ST   R1, [R7]           ; DISPLAY = tag|6
        LDI  R7, V_SPIN
        LD   R5, [R7]
        LDI  R7, T_LIMIT
        ST   R5, [R7]           ; LIMIT = spin ticks
        LDI  R7, T_CTRL
        LDI  R1, 0x03
        ST   R1, [R7]           ; clear + re-arm
        LDI  R1, A_SPIN
        ST   R1, [R6]
        LDI  R0, IN_STATUS
        LDI  R4, 0x10
        LDI  R7, T_STATUS
spin:   LD   R1, [R0]
        AND  R1, R4
        BNEZ R1, trip_fault
        LD   R1, [R7]
        BEQZ R1, spin
; ---------------- STOP: actuators off, wait drum stop, unlock, buzzer ----
        LDI  R1, A_LOCK
        ST   R1, [R6]           ; motor + pump off, door still locked
        LDI  R7, T_CTRL
        LDI  R1, 0x02
        ST   R1, [R7]           ; stop + clear timer
        LDI  R7, V_TAG
        LD   R1, [R7]
        ADDI R1, 0x07
        LDI  R7, DISPLAY
        ST   R1, [R7]           ; DISPLAY = tag|7
        LDI  R7, DRUM_RPM
wait_drum:
        LD   R1, [R7]
        BNEZ R1, wait_drum      ; unlock only after the drum has stopped
        LDI  R1, A_DONE
        ST   R1, [R6]           ; BUZZER on, DOOR_LOCK off
        LDI  R7, V_TAG
        LD   R1, [R7]
        ADDI R1, 0x08
        LDI  R7, DISPLAY
        ST   R1, [R7]           ; DISPLAY = tag|8 (done)
release:
        LDI  R7, IN_STATUS
wait_rel:
        LD   R1, [R7]
        LDI  R2, 0x01
        AND  R2, R1
        BNEZ R2, wait_rel       ; wait until START is released
        JMP  idle_wait          ; buzzer stays on until the next START
; ---------------- fault handlers ---------------------------------------
door_abort:
        LDI  R1, A_OFF
        ST   R1, [R6]           ; unlock, everything off
        LDI  R7, DISPLAY
        LDI  R1, 0xE1
        ST   R1, [R7]
        JMP  release
trip_fault:
        LDI  R1, A_OFF
        ST   R1, [R6]           ; software clears MOTOR_EN request (needed for re-arm)
        LDI  R7, T_CTRL
        LDI  R1, 0x02
        ST   R1, [R7]           ; stop timer
        LDI  R7, DISPLAY
        LDI  R1, 0xEE
        ST   R1, [R7]
        LDI  R7, IN_STATUS
        LDI  R4, 0x10
wait_rearm:
        LD   R1, [R7]
        AND  R1, R4
        BNEZ R1, wait_rearm     ; TRIP clears only after door closed + new START edge
        JMP  idle_wait          ; re-armed: START is held, a fresh cycle begins
