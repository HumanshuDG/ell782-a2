; t1_hazards.asm - Section 8.1 / 8.2 / 8.3 and validation group 1
        LDI  R1, 0x01
        LDI  R2, 0x10          ; ALU operand and RAM address
        LDI  R3, 0x03
        LDI  R4, 0x20          ; RAM address for 8.3
        ST   R3, [R2]          ; RAM[0x10] = 0x03 (initialise before the load)
        NOP
; ---- 8.1 ALU forwarding, no stall
        ADD  R1, R2            ; R1 = 0x11
        SUB  R3, R1            ; R3 = 0x03-0x11 = 0xF2   (R1 from EX/MEM)
; ---- 8.2 load-use, exactly one stall
        LD   R1, [R2]          ; R1 = RAM[0x10] = 0x03
        ADD  R3, R1            ; 1 bubble, R1 from MEM/WB: R3 = 0xF5
; ---- 8.3 youngest producer to store data
        ADD  R1, R2            ; R1 = 0x13
        SUB  R1, R3            ; R1 = 0x13-0xF5 = 0x1E  (youngest writer of R1)
        ST   R1, [R4]          ; RAM[0x20] = 0x1E   (EX/MEM beats MEM/WB)
        LD   R5, [R4]          ; R5 = 0x1E
        LDI  R7, 0xF5
        ST   R5, [R7]          ; DISPLAY = 0x1E
        HALT
        LDI  R6, 0xFF          ; younger than HALT: never executes
        ST   R6, [R7]
