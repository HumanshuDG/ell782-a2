; t2_branch_halt.asm - Section 8.4 and validation group 2
        LDI  R2, 0x21          ; LOCK|VALVE pattern (would open the valve)
        LDI  R4, 0xF4          ; Rvalve = actuator latch
        LDI  R3, 0x07
        LDI  R1, 0x09
        LDI  R7, 0xF5          ; DISPLAY
; ---- 8.4 taken branch kills a wrong-path actuator store
        SUB  R1, R1            ; R1 = 0
        BEQZ R1, target1       ; taken, R1 forwarded from EX/MEM
        ST   R2, [R4]          ; wrong path: must not write the valve
        ADD  R3, R4            ; wrong path
target1:
        BNEZ R1, bad           ; not taken (R1 = 0)
        BNEZ R3, target2       ; taken (R3 = 7)
        HALT                   ; wrong-path HALT: flushed, must not stop
        ST   R2, [R4]          ; wrong path
target2:
        ST   R3, [R7]          ; DISPLAY = 0x07 (R3 untouched by wrong path)
        JMP  target3
        HALT                   ; wrong-path HALT behind a jump
        HALT
target3:
        LDI  R6, 0xAA
        ST   R6, [R7]          ; DISPLAY = 0xAA: execution continued
        HALT                   ; real HALT
        ST   R2, [R4]          ; younger than HALT: killed
        LDI  R6, 0x55
bad:    LDI  R6, 0xBD
        ST   R6, [R7]
        HALT
