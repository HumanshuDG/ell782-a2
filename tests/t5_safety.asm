; t5_safety.asm - validation group 5: motor interlock and explicit re-arm
        LDI  R7, 0xF4          ; ACT
        LDI  R6, 0xF0          ; IN_STATUS
        LDI  R5, 0xF5          ; DISPLAY
        LDI  R4, 0x01          ; START mask
        LDI  R3, 0x10          ; TRIP mask
        LDI  R1, 0x24
        ST   R1, [R7]          ; request DOOR_LOCK + MOTOR_EN
        LDI  R1, 0x01
        ST   R1, [R5]          ; DISPLAY = 1 : motor requested
waitS:  LD   R2, [R6]
        AND  R2, R4
        BEQZ R2, waitS         ; wait for a START press (request still active)
waitR:  LD   R2, [R6]
        AND  R2, R4
        BNEZ R2, waitR         ; wait for START release
        LDI  R1, 0x20
        ST   R1, [R7]          ; software clears MOTOR_EN request
        LDI  R1, 0x02
        ST   R1, [R5]          ; DISPLAY = 2 : waiting for re-arm
waitT:  LD   R2, [R6]
        AND  R2, R3
        BNEZ R2, waitT         ; until hardware TRIP is cleared
        LDI  R1, 0x24
        ST   R1, [R7]          ; request motor again
        LDI  R1, 0x03
        ST   R1, [R5]          ; DISPLAY = 3 : running again
        HALT
