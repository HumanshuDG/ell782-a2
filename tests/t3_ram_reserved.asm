; t3_ram_reserved.asm - validation group 3: RAM store/load + reserved isolation
        LDI  R1, 0x5A
        LDI  R2, 0x00
        ST   R1, [R2]          ; RAM[0x00] = 0x5A
        LDI  R3, 0x33
        LDI  R2, 0x6F
        ST   R3, [R2]          ; RAM[0x6F] = 0x33
        LDI  R3, 0xA5
        LDI  R2, 0x7F
        ST   R3, [R2]          ; RAM[0x7F] = 0xA5
        LDI  R5, 0x77
        LDI  R4, 0x80
        ST   R5, [R4]          ; reserved 0x80: ignored (would alias RAM[0x00])
        LDI  R4, 0xEF
        ST   R5, [R4]          ; reserved 0xEF: ignored (would alias RAM[0x6F])
        LDI  R4, 0xFF
        ST   R5, [R4]          ; unimplemented peripheral: ignored (alias RAM[0x7F])
        LDI  R4, 0xF0
        ST   R5, [R4]          ; read-only IN_STATUS: ignored
        LD   R6, [R2]          ; R6 = RAM[0x7F] = 0xA5
        LDI  R2, 0x00
        LD   R7, [R2]          ; R7 = RAM[0x00] = 0x5A
        LDI  R2, 0x6F
        LD   R1, [R2]          ; R1 = RAM[0x6F] = 0x33
        LDI  R4, 0x80
        LD   R0, [R4]          ; R0 = 0x00 (reserved reads 0)
        LDI  R4, 0xEF
        LD   R3, [R4]          ; R3 = 0x00
        LDI  R4, 0xF7
        LD   R5, [R4]          ; R5 = 0x00 (unimplemented peripheral)
        LDI  R4, 0xF5
        ST   R6, [R4]          ; DISPLAY = 0xA5
        HALT
