; t4_timer.asm - validation group 4: count, sticky MATCH, clear/re-arm, no
; retroactive MATCH, wrap-around, ticking during stalls and after HALT
        LDI  R7, 0xF9          ; T_LIMIT
        LDI  R6, 0xFA          ; T_CTRL
        LDI  R5, 0xFB          ; T_STATUS
        LDI  R4, 0xF8          ; T_COUNT
        LDI  R1, 6
        ST   R1, [R7]          ; LIMIT = 6
        LDI  R1, 0x03
        ST   R1, [R6]          ; interval 1: clear + enable
poll1:  LD   R2, [R5]
        BEQZ R2, poll1         ; load-use stall every iteration (timer keeps counting)
        LD   R3, [R4]          ; COUNT kept counting past LIMIT
        LD   R2, [R5]          ; MATCH still 1 (sticky)
        LDI  R1, 10
        ST   R1, [R7]          ; LIMIT = 10
        LDI  R1, 0x03
        ST   R1, [R6]          ; interval 2: clear COUNT+MATCH, re-arm
        LD   R2, [R5]          ; MATCH = 0 after clear
poll2:  LD   R2, [R5]
        BEQZ R2, poll2
        LDI  R1, 0x00
        ST   R1, [R7]          ; LIMIT = 0 (comparison disabled)
        LDI  R1, 0x03
        ST   R1, [R6]          ; clear + enable
        NOP
        NOP
        NOP
        LDI  R1, 0x00
        ST   R1, [R6]          ; disable (no clear): COUNT frozen
        LD   R3, [R4]          ; R3 = frozen COUNT
        ST   R3, [R7]          ; LIMIT = COUNT -> MATCH must stay 0
        LD   R2, [R5]          ; R2 = 0
        LDI  R1, 0xF5
        ST   R2, [R1]          ; DISPLAY = MATCH = 0
        LDI  R1, 0x03
        ST   R1, [R7]          ; LIMIT = 3
        LDI  R1, 0x01
        ST   R1, [R6]          ; enable, no clear: COUNT runs ..FF -> 00 -> 03 => MATCH
        HALT                   ; timer keeps ticking while halted
