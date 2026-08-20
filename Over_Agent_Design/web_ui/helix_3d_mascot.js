/*
 * Helix real-time mascot.
 *
 * This procedural model stays fully local: no remote model, texture, CDN, or
 * video is required. Its geometry follows the official mascot's round robot
 * face, twin antennae, and metallic circuit strands wrapped as a double helix.
 */

class Helix3DMascot {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas || !window.THREE) {
            this.showFallback();
            return;
        }

        try {
            this.scene = new THREE.Scene();
            this.camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
            this.camera.position.set(0, 0.15, 10.2);
            this.renderer = new THREE.WebGLRenderer({
                canvas: this.canvas,
                alpha: true,
                antialias: true,
                powerPreference: "high-performance"
            });
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
            this.renderer.outputEncoding = THREE.sRGBEncoding;
            this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
            this.renderer.toneMappingExposure = 1.25;

            this.clock = new THREE.Clock();
            this.pointerTarget = new THREE.Vector2();
            this.pointerCurrent = new THREE.Vector2();
            this.isSpeaking = false;
            this.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            this.colorMaterials = [];
            this.moods = {
                focused: { primary: 0x49efff, secondary: 0x5578ff, accent: 0xdffeff },
                excited: { primary: 0xff4fc8, secondary: 0xffb340, accent: 0xfff1bc },
                calm: { primary: 0x55f3c1, secondary: 0x51bfff, accent: 0xe5fff8 },
                reflective: { primary: 0xc968ff, secondary: 0x526dff, accent: 0xf2dcff }
            };

            this.buildLights();
            this.buildMascot();
            this.bindEvents();
            this.resize();
            this.animate();
        } catch (error) {
            console.error("Unable to initialize the Helix WebGL mascot", error);
            this.showFallback();
        }
    }

    showFallback() {
        const host = this.canvas && this.canvas.closest(".avatar-core-mascot-3d");
        if (host) host.classList.add("webgl-unavailable");
    }

    buildLights() {
        this.scene.add(new THREE.HemisphereLight(0xdffcff, 0x07101e, 2.15));
        this.keyLight = new THREE.PointLight(0x49efff, 4.8, 24);
        this.keyLight.position.set(4.5, 5.5, 7);
        this.scene.add(this.keyLight);
        this.rimLight = new THREE.PointLight(0x7c5cff, 4.2, 22);
        this.rimLight.position.set(-4.5, 0, 4);
        this.scene.add(this.rimLight);
        const warmLight = new THREE.PointLight(0xffc878, 2.4, 15);
        warmLight.position.set(0, -3.5, 5);
        this.scene.add(warmLight);
    }

    makeMetal(channel, color, emissiveIntensity = 0.16) {
        const material = new THREE.MeshStandardMaterial({
            color,
            metalness: 0.82,
            roughness: 0.2,
            emissive: color,
            emissiveIntensity
        });
        material.userData.colorChannel = channel;
        this.colorMaterials.push(material);
        return material;
    }

    makeGlow(channel, color) {
        const material = new THREE.MeshBasicMaterial({ color });
        material.userData.colorChannel = channel;
        this.colorMaterials.push(material);
        return material;
    }

    tubeFromPoints(points, radius, material, radialSegments = 12) {
        const curve = new THREE.CatmullRomCurve3(points);
        return new THREE.Mesh(
            new THREE.TubeGeometry(curve, Math.max(24, points.length * 8), radius, radialSegments, false),
            material
        );
    }

    cylinderBetween(start, end, radius, material) {
        const direction = new THREE.Vector3().subVectors(end, start);
        const mesh = new THREE.Mesh(
            new THREE.CylinderGeometry(radius, radius, direction.length(), 10),
            material
        );
        mesh.position.copy(start).add(end).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(
            new THREE.Vector3(0, 1, 0),
            direction.clone().normalize()
        );
        return mesh;
    }

    buildMascot() {
        this.character = new THREE.Group();
        this.character.rotation.x = -0.035;
        this.scene.add(this.character);

        const primaryMetal = this.makeMetal("primary", 0x49efff, 0.2);
        const secondaryMetal = this.makeMetal("secondary", 0x5578ff, 0.16);
        const darkMetal = new THREE.MeshStandardMaterial({
            color: 0x102b43,
            metalness: 0.9,
            roughness: 0.17,
            emissive: 0x061321,
            emissiveIntensity: 0.32
        });
        const paleMetal = new THREE.MeshStandardMaterial({
            color: 0xc7f7f2,
            metalness: 0.48,
            roughness: 0.13,
            emissive: 0x75d9e5,
            emissiveIntensity: 0.13
        });
        const faceMaterial = new THREE.MeshStandardMaterial({
            color: 0xeafff9,
            metalness: 0.12,
            roughness: 0.12,
            emissive: 0x8cecf1,
            emissiveIntensity: 0.14
        });
        const featureMaterial = new THREE.MeshBasicMaterial({ color: 0x12324b });
        this.accentGlow = this.makeGlow("accent", 0xdffeff);

        this.bodyCore = new THREE.Mesh(new THREE.SphereGeometry(1.05, 40, 28), darkMetal);
        this.bodyCore.position.set(0, -0.72, -0.08);
        this.bodyCore.scale.set(0.92, 1.65, 0.7);
        this.character.add(this.bodyCore);

        this.helixGroup = new THREE.Group();
        this.character.add(this.helixGroup);
        this.helixStrands = [];
        [
            { phase: 0, material: primaryMetal },
            { phase: Math.PI, material: secondaryMetal }
        ].forEach(({ phase, material }, strandIndex) => {
            const points = [];
            const samples = 54;
            for (let i = 0; i <= samples; i += 1) {
                const t = i / samples;
                const angle = t * Math.PI * 2 * 1.12 + phase;
                const shoulderTaper = 0.9 + Math.sin(t * Math.PI) * 0.16;
                points.push(new THREE.Vector3(
                    Math.sin(angle) * 1.23 * shoulderTaper,
                    1.48 - t * 4.05,
                    Math.cos(angle) * 0.48 - 0.15
                ));
            }
            const strand = this.tubeFromPoints(points, 0.245, material, 16);
            strand.userData.phase = phase;
            this.helixGroup.add(strand);
            this.helixStrands.push(strand);

            const highlightPoints = points.map((point) => new THREE.Vector3(
                point.x * 1.015,
                point.y,
                point.z + 0.205
            ));
            const highlight = this.tubeFromPoints(
                highlightPoints,
                0.035,
                strandIndex === 0 ? this.accentGlow : this.makeGlow("secondary", 0x5578ff),
                7
            );
            this.helixGroup.add(highlight);
        });

        const rungMaterial = new THREE.MeshStandardMaterial({
            color: 0xa7ecee,
            metalness: 0.72,
            roughness: 0.18,
            emissive: 0x4bcbd7,
            emissiveIntensity: 0.12
        });
        for (let index = 0; index < 5; index += 1) {
            const t = 0.52 + index * 0.095;
            const angle = t * Math.PI * 2 * 1.12;
            const left = new THREE.Vector3(
                Math.sin(angle) * 1.08,
                1.48 - t * 4.05,
                Math.cos(angle) * 0.36 - 0.16
            );
            const right = new THREE.Vector3(
                Math.sin(angle + Math.PI) * 1.08,
                left.y,
                Math.cos(angle + Math.PI) * 0.36 - 0.16
            );
            this.helixGroup.add(this.cylinderBetween(left, right, 0.055, rungMaterial));
            [left, right].forEach((point) => {
                const node = new THREE.Mesh(new THREE.SphereGeometry(0.105, 12, 10), this.accentGlow);
                node.position.copy(point);
                this.helixGroup.add(node);
            });
        }

        this.buildHead({ darkMetal, paleMetal, faceMaterial, featureMaterial, primaryMetal, secondaryMetal });
        this.buildCircuitDetails(primaryMetal, secondaryMetal);
        this.buildEnergyField();
    }

    buildHead(materials) {
        const { darkMetal, paleMetal, faceMaterial, featureMaterial, primaryMetal, secondaryMetal } = materials;
        this.headGroup = new THREE.Group();
        this.headGroup.position.set(0, 1.47, 0.12);
        this.character.add(this.headGroup);

        const helmet = new THREE.Mesh(new THREE.SphereGeometry(1.08, 48, 36), darkMetal);
        helmet.scale.set(1.03, 0.98, 0.84);
        this.headGroup.add(helmet);
        const helmetRing = new THREE.Mesh(new THREE.TorusGeometry(1.02, 0.155, 14, 64), primaryMetal);
        helmetRing.position.z = 0.18;
        this.headGroup.add(helmetRing);
        const face = new THREE.Mesh(new THREE.SphereGeometry(0.82, 44, 32), faceMaterial);
        face.position.z = 0.72;
        face.scale.set(1, 0.93, 0.27);
        this.headGroup.add(face);

        [-1, 1].forEach((side) => {
            const ear = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.24, 24), secondaryMetal);
            ear.position.set(side * 1.03, -0.05, 0.03);
            ear.rotation.z = Math.PI / 2;
            this.headGroup.add(ear);
            const antenna = this.tubeFromPoints([
                new THREE.Vector3(side * 0.46, 0.76, 0),
                new THREE.Vector3(side * 0.56, 1.18, 0.02),
                new THREE.Vector3(side * 0.78, 1.47, 0.08)
            ], 0.065, side < 0 ? primaryMetal : secondaryMetal, 10);
            this.headGroup.add(antenna);
            const tip = new THREE.Mesh(
                new THREE.SphereGeometry(0.16, 18, 14),
                side < 0 ? this.accentGlow : secondaryMetal
            );
            tip.position.set(side * 0.78, 1.48, 0.08);
            this.headGroup.add(tip);
        });

        this.eyeGroup = new THREE.Group();
        this.eyeGroup.position.z = 1.005;
        this.headGroup.add(this.eyeGroup);
        [-1, 1].forEach((side) => {
            const eye = this.tubeFromPoints([
                new THREE.Vector3(side * 0.48 - 0.16, 0.13, 0),
                new THREE.Vector3(side * 0.48, 0.27, 0),
                new THREE.Vector3(side * 0.48 + 0.16, 0.13, 0)
            ], 0.055, featureMaterial, 8);
            this.eyeGroup.add(eye);
        });

        this.mouth = this.tubeFromPoints([
            new THREE.Vector3(-0.34, -0.23, 1.018),
            new THREE.Vector3(0, -0.46, 1.038),
            new THREE.Vector3(0.34, -0.23, 1.018)
        ], 0.058, featureMaterial, 8);
        this.headGroup.add(this.mouth);
        [-1, 1].forEach((side) => {
            const cheek = new THREE.Mesh(new THREE.SphereGeometry(0.075, 10, 8), this.accentGlow);
            cheek.position.set(side * 0.59, -0.23, 1.005);
            cheek.scale.set(1.6, 0.55, 0.4);
            this.headGroup.add(cheek);
        });
        const brow = this.tubeFromPoints([
            new THREE.Vector3(-0.62, 0.61, 0.82),
            new THREE.Vector3(0, 0.76, 0.9),
            new THREE.Vector3(0.62, 0.61, 0.82)
        ], 0.075, paleMetal, 10);
        this.headGroup.add(brow);
    }

    buildCircuitDetails(primaryMetal, secondaryMetal) {
        const circuitGroup = new THREE.Group();
        circuitGroup.position.set(0, -0.66, 0.76);
        this.character.add(circuitGroup);
        const centerRing = new THREE.Mesh(new THREE.TorusGeometry(0.35, 0.075, 12, 36), primaryMetal);
        circuitGroup.add(centerRing);
        const center = new THREE.Mesh(new THREE.SphereGeometry(0.22, 20, 16), this.accentGlow);
        center.scale.z = 0.45;
        circuitGroup.add(center);
        const circuitMaterial = this.makeGlow("primary", 0x49efff);
        [
            [-0.38, -0.02, -0.82, 0.18],
            [0.38, 0.04, 0.82, 0.3],
            [-0.24, -0.36, -0.55, -0.72],
            [0.24, -0.36, 0.62, -0.68]
        ].forEach(([x1, y1, x2, y2]) => {
            const trace = this.tubeFromPoints([
                new THREE.Vector3(x1, y1, 0),
                new THREE.Vector3((x1 + x2) * 0.5, y2, 0),
                new THREE.Vector3(x2, y2, 0)
            ], 0.025, circuitMaterial, 6);
            circuitGroup.add(trace);
            const node = new THREE.Mesh(new THREE.SphereGeometry(0.065, 10, 8), secondaryMetal);
            node.position.set(x2, y2, 0);
            circuitGroup.add(node);
        });
    }

    buildEnergyField() {
        this.energyRings = new THREE.Group();
        this.energyRings.position.set(0, -0.38, -0.2);
        this.character.add(this.energyRings);
        [
            { radius: 1.55, rotation: [1.18, 0.18, 0.18], channel: "primary", color: 0x49efff },
            { radius: 1.38, rotation: [1.08, -0.22, -0.25], channel: "secondary", color: 0x5578ff }
        ].forEach((ringSpec) => {
            const ring = new THREE.Mesh(
                new THREE.TorusGeometry(ringSpec.radius, 0.025, 8, 72),
                this.makeGlow(ringSpec.channel, ringSpec.color)
            );
            ring.rotation.set(...ringSpec.rotation);
            this.energyRings.add(ring);
        });

        const particlePositions = [];
        for (let index = 0; index < 42; index += 1) {
            const angle = (index / 42) * Math.PI * 2;
            const radius = 1.6 + (index % 5) * 0.085;
            particlePositions.push(
                Math.cos(angle) * radius,
                -0.35 + Math.sin(angle * 3) * 1.75,
                -0.5 + Math.sin(angle) * 0.7
            );
        }
        const particleGeometry = new THREE.BufferGeometry();
        particleGeometry.setAttribute("position", new THREE.Float32BufferAttribute(particlePositions, 3));
        this.particles = new THREE.Points(
            particleGeometry,
            new THREE.PointsMaterial({
                color: 0x86f8ff,
                size: 0.055,
                transparent: true,
                opacity: 0.78,
                depthWrite: false
            })
        );
        this.character.add(this.particles);
    }

    bindEvents() {
        this.canvas.addEventListener("webglcontextlost", (event) => {
            event.preventDefault();
            this.showFallback();
        });
        this.onPointerMove = (event) => {
            this.pointerTarget.set(
                (event.clientX / Math.max(window.innerWidth, 1)) * 2 - 1,
                -(event.clientY / Math.max(window.innerHeight, 1)) * 2 + 1
            );
        };
        window.addEventListener("pointermove", this.onPointerMove, { passive: true });
        if (window.ResizeObserver) {
            this.resizeObserver = new ResizeObserver(() => this.resize());
            this.resizeObserver.observe(this.canvas);
        } else {
            window.addEventListener("resize", () => this.resize());
        }
    }

    resize() {
        if (!this.renderer || !this.canvas) return;
        const width = Math.max(1, this.canvas.clientWidth);
        const height = Math.max(1, this.canvas.clientHeight);
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    }

    setMood(moodName) {
        const mood = this.moods[moodName] || this.moods.focused;
        this.colorMaterials.forEach((material) => {
            const channel = material.userData.colorChannel || "primary";
            const color = mood[channel];
            material.color.setHex(color);
            if (material.emissive) material.emissive.setHex(color);
        });
        this.keyLight.color.setHex(mood.primary);
        this.rimLight.color.setHex(mood.secondary);
    }

    setSpeaking(isSpeaking) {
        this.isSpeaking = Boolean(isSpeaking);
    }

    animate() {
        if (!this.renderer) return;
        requestAnimationFrame(() => this.animate());
        const elapsed = this.clock.getElapsedTime();
        const motion = this.reduceMotion ? 0.2 : 1;
        this.pointerCurrent.lerp(this.pointerTarget, 0.055);
        this.character.position.y = Math.sin(elapsed * 1.45) * 0.13 * motion;
        this.character.rotation.z = Math.sin(elapsed * 0.72) * 0.025 * motion;
        this.character.rotation.x = -0.035 - this.pointerCurrent.y * 0.1 * motion;
        this.character.rotation.y = this.pointerCurrent.x * 0.24 * motion + Math.sin(elapsed * 0.42) * 0.07 * motion;
        this.helixGroup.rotation.y = Math.sin(elapsed * 0.78) * 0.085 * motion;
        this.headGroup.rotation.y = this.pointerCurrent.x * 0.08 * motion;
        this.headGroup.rotation.x = -this.pointerCurrent.y * 0.045 * motion;
        this.energyRings.rotation.y = elapsed * 0.24 * motion;
        this.energyRings.rotation.z = Math.sin(elapsed * 0.55) * 0.12 * motion;
        this.particles.rotation.y = -elapsed * 0.09 * motion;

        const blinkCycle = elapsed % 4.7;
        const blink = blinkCycle > 4.51 ? Math.max(0.12, Math.abs(blinkCycle - 4.60) * 11) : 1;
        this.eyeGroup.scale.y = blink;
        const speakingPulse = this.isSpeaking ? 0.82 + Math.abs(Math.sin(elapsed * 9)) * 0.48 : 1;
        this.mouth.scale.y = speakingPulse;
        const corePulse = 1 + Math.sin(elapsed * 3.1) * 0.06 * motion;
        this.bodyCore.scale.x = 0.92 * corePulse;
        this.bodyCore.scale.z = 0.7 * corePulse;
        this.renderer.render(this.scene, this.camera);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.helix3DMascot = new Helix3DMascot("helix-3d-canvas");
});
