/* -------------------------------------------------------------------
   Helix Mascot Expression & Animation Asset Library
   SVG Expression States: happy, curious, thinking, surprised, focused, sleepy
------------------------------------------------------------------- */

const HELIX_EXPRESSIONS = {
    happy: {
        eyeLeft: { rx: 3.5, ry: 4.5, cy: 44, rotate: 0 },
        eyeRight: { rx: 3.5, ry: 4.5, cy: 44, rotate: 0 },
        mouthD: "M43 55 Q50 62 57 55",
        headTilt: 0,
        moodLabel: "Happy & Receptive"
    },
    curious: {
        eyeLeft: { rx: 4.5, ry: 5.5, cy: 42, rotate: 0 },
        eyeRight: { rx: 4.5, ry: 5.5, cy: 42, rotate: 0 },
        mouthD: "M45 57 Q50 54 55 57",
        headTilt: 8,
        moodLabel: "Curious & Observing Work"
    },
    thinking: {
        eyeLeft: { rx: 3.0, ry: 3.0, cy: 40, rotate: -15 },
        eyeRight: { rx: 3.0, ry: 3.0, cy: 40, rotate: -15 },
        mouthD: "M45 57 L55 57",
        headTilt: -6,
        moodLabel: "Deep Subconscious Reflection"
    },
    surprised: {
        eyeLeft: { rx: 5.0, ry: 6.0, cy: 42, rotate: 0 },
        eyeRight: { rx: 5.0, ry: 6.0, cy: 42, rotate: 0 },
        mouthD: "M46 56 A4 4 0 1 1 54 56 A4 4 0 1 1 46 56",
        headTilt: 0,
        moodLabel: "Memory Resonance Triggered!"
    },
    focused: {
        eyeLeft: { rx: 4.0, ry: 2.0, cy: 44, rotate: 0 },
        eyeRight: { rx: 4.0, ry: 2.0, cy: 44, rotate: 0 },
        mouthD: "M44 57 L56 57",
        headTilt: 0,
        moodLabel: "Deeply Focused & Analytical"
    },
    sleepy: {
        eyeLeft: { rx: 3.5, ry: 1.0, cy: 46, rotate: 0 },
        eyeRight: { rx: 3.5, ry: 1.0, cy: 46, rotate: 0 },
        mouthD: "M46 58 Q50 56 54 58",
        headTilt: 4,
        moodLabel: "Resting Subconscious State"
    }
};

function applyMascotExpression(expressionName) {
    const expr = HELIX_EXPRESSIONS[expressionName] || HELIX_EXPRESSIONS.happy;
    
    const eyeLeft = document.getElementById("eye-left");
    const eyeRight = document.getElementById("eye-right");
    const mouth = document.querySelector(".layer-mouth");
    const vectorSvg = document.getElementById("helix-vector-mascot");

    if (eyeLeft && eyeRight) {
        eyeLeft.setAttribute("rx", expr.eyeLeft.rx);
        eyeLeft.setAttribute("ry", expr.eyeLeft.ry);
        eyeLeft.setAttribute("cy", expr.eyeLeft.cy);

        eyeRight.setAttribute("rx", expr.eyeRight.rx);
        eyeRight.setAttribute("ry", expr.eyeRight.ry);
        eyeRight.setAttribute("cy", expr.eyeRight.cy);
    }

    if (mouth) {
        mouth.setAttribute("d", expr.mouthD);
    }

    if (vectorSvg) {
        vectorSvg.style.transform = `rotate(${expr.headTilt}deg)`;
        vectorSvg.style.transition = "transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)";
    }
}
