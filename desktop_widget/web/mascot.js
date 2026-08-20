/*
 * Dependency-free WebGL Helix mascot.
 *
 * The geometry is generated locally and rendered with a real perspective
 * camera, depth testing, surface normals, and animated lighting.  No CDN,
 * video, raster avatar, model service, or memory/runtime module is involved.
 */

(function () {
  "use strict";

  const M4 = {
    identity() {
      return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    },
    multiply(a, b) {
      const out = new Array(16).fill(0);
      for (let column = 0; column < 4; column += 1) {
        for (let row = 0; row < 4; row += 1) {
          for (let index = 0; index < 4; index += 1) {
            out[column * 4 + row] += a[index * 4 + row] * b[column * 4 + index];
          }
        }
      }
      return out;
    },
    perspective(fieldOfView, aspect, near, far) {
      const f = 1 / Math.tan(fieldOfView / 2);
      const range = 1 / (near - far);
      return [
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (near + far) * range, -1,
        0, 0, near * far * range * 2, 0,
      ];
    },
    translation(x, y, z) {
      return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
    },
    scaling(x, y, z) {
      return [x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1];
    },
    rotationX(angle) {
      const c = Math.cos(angle);
      const s = Math.sin(angle);
      return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1];
    },
    rotationY(angle) {
      const c = Math.cos(angle);
      const s = Math.sin(angle);
      return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
    },
    rotationZ(angle) {
      const c = Math.cos(angle);
      const s = Math.sin(angle);
      return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    },
    compose(position, rotation, scale) {
      let matrix = M4.translation(position[0], position[1], position[2]);
      matrix = M4.multiply(matrix, M4.rotationZ(rotation[2]));
      matrix = M4.multiply(matrix, M4.rotationY(rotation[1]));
      matrix = M4.multiply(matrix, M4.rotationX(rotation[0]));
      return M4.multiply(matrix, M4.scaling(scale[0], scale[1], scale[2]));
    },
  };

  function normalize(vector) {
    const length = Math.hypot(vector[0], vector[1], vector[2]) || 1;
    return [vector[0] / length, vector[1] / length, vector[2] / length];
  }

  function cross(a, b) {
    return [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0],
    ];
  }

  function hexToRgb(hex) {
    return [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255];
  }

  function makeSphere(latitudeBands = 16, longitudeBands = 22) {
    const positions = [];
    const normals = [];
    const indices = [];
    for (let latitude = 0; latitude <= latitudeBands; latitude += 1) {
      const theta = (latitude / latitudeBands) * Math.PI;
      const sinTheta = Math.sin(theta);
      const cosTheta = Math.cos(theta);
      for (let longitude = 0; longitude <= longitudeBands; longitude += 1) {
        const phi = (longitude / longitudeBands) * Math.PI * 2;
        const x = Math.cos(phi) * sinTheta;
        const y = cosTheta;
        const z = Math.sin(phi) * sinTheta;
        positions.push(x, y, z);
        normals.push(x, y, z);
      }
    }
    for (let latitude = 0; latitude < latitudeBands; latitude += 1) {
      for (let longitude = 0; longitude < longitudeBands; longitude += 1) {
        const first = latitude * (longitudeBands + 1) + longitude;
        const second = first + longitudeBands + 1;
        indices.push(first, second, first + 1, second, second + 1, first + 1);
      }
    }
    return { positions, normals, indices };
  }

  function makeCylinder(segments = 18) {
    const positions = [];
    const normals = [];
    const indices = [];
    for (let row = 0; row <= 1; row += 1) {
      const y = row - 0.5;
      for (let segment = 0; segment <= segments; segment += 1) {
        const angle = (segment / segments) * Math.PI * 2;
        const x = Math.cos(angle);
        const z = Math.sin(angle);
        positions.push(x, y, z);
        normals.push(x, 0, z);
      }
    }
    for (let segment = 0; segment < segments; segment += 1) {
      const nextRow = segments + 1;
      indices.push(segment, nextRow + segment, segment + 1);
      indices.push(nextRow + segment, nextRow + segment + 1, segment + 1);
    }
    return { positions, normals, indices };
  }

  function makeTorus(majorSegments = 40, minorSegments = 10, minorRadius = 0.1) {
    const positions = [];
    const normals = [];
    const indices = [];
    for (let major = 0; major <= majorSegments; major += 1) {
      const u = (major / majorSegments) * Math.PI * 2;
      for (let minor = 0; minor <= minorSegments; minor += 1) {
        const v = (minor / minorSegments) * Math.PI * 2;
        const radial = 1 + minorRadius * Math.cos(v);
        const x = radial * Math.cos(u);
        const y = radial * Math.sin(u);
        const z = minorRadius * Math.sin(v);
        positions.push(x, y, z);
        normals.push(Math.cos(v) * Math.cos(u), Math.cos(v) * Math.sin(u), Math.sin(v));
      }
    }
    const rowLength = minorSegments + 1;
    for (let major = 0; major < majorSegments; major += 1) {
      for (let minor = 0; minor < minorSegments; minor += 1) {
        const first = major * rowLength + minor;
        const second = first + rowLength;
        indices.push(first, second, first + 1, second, second + 1, first + 1);
      }
    }
    return { positions, normals, indices };
  }

  class HelixMascot {
    constructor(canvas) {
      this.canvas = canvas;
      this.host = canvas.closest(".helix-avatar");
      this.gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        depth: true,
        premultipliedAlpha: true,
      });
      if (!this.gl) throw new Error("WebGL is unavailable");

      this.pointerTarget = [0, 0];
      this.pointer = [0, 0];
      this.speaking = false;
      this.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.startTime = performance.now();
      this.moodName = "focused";
      this.moods = {
        focused: { primary: 0x55efff, secondary: 0x6578ff, accent: 0xdffeff },
        active: { primary: 0xff62cb, secondary: 0xffb64a, accent: 0xfff0c2 },
        resting: { primary: 0x65efc3, secondary: 0x58bfff, accent: 0xe7fff8 },
        dormant: { primary: 0xb57aff, secondary: 0x6075ff, accent: 0xf0e2ff },
        unknown: { primary: 0x55efff, secondary: 0x6578ff, accent: 0xdffeff },
      };

      this.program = this.createProgram();
      this.locations = {
        position: this.gl.getAttribLocation(this.program, "aPosition"),
        normal: this.gl.getAttribLocation(this.program, "aNormal"),
        world: this.gl.getUniformLocation(this.program, "uWorld"),
        viewProjection: this.gl.getUniformLocation(this.program, "uViewProjection"),
        color: this.gl.getUniformLocation(this.program, "uColor"),
        glow: this.gl.getUniformLocation(this.program, "uGlow"),
      };
      this.meshes = {
        sphere: this.uploadMesh(makeSphere()),
        cylinder: this.uploadMesh(makeCylinder()),
        torus: this.uploadMesh(makeTorus()),
      };

      this.gl.enable(this.gl.DEPTH_TEST);
      this.gl.enable(this.gl.CULL_FACE);
      this.gl.cullFace(this.gl.BACK);
      this.gl.clearColor(0, 0, 0, 0);
      this.bindEvents();
      this.render = this.render.bind(this);
      window.requestAnimationFrame(this.render);
    }

    createShader(type, source) {
      const shader = this.gl.createShader(type);
      this.gl.shaderSource(shader, source);
      this.gl.compileShader(shader);
      if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
        throw new Error(this.gl.getShaderInfoLog(shader) || "Unable to compile WebGL shader");
      }
      return shader;
    }

    createProgram() {
      const vertex = this.createShader(this.gl.VERTEX_SHADER, `
        attribute vec3 aPosition;
        attribute vec3 aNormal;
        uniform mat4 uWorld;
        uniform mat4 uViewProjection;
        varying vec3 vNormal;
        varying vec3 vWorldPosition;
        void main() {
          vec4 worldPosition = uWorld * vec4(aPosition, 1.0);
          vWorldPosition = worldPosition.xyz;
          vNormal = normalize(mat3(uWorld) * aNormal);
          gl_Position = uViewProjection * worldPosition;
        }
      `);
      const fragment = this.createShader(this.gl.FRAGMENT_SHADER, `
        precision mediump float;
        uniform vec3 uColor;
        uniform float uGlow;
        varying vec3 vNormal;
        varying vec3 vWorldPosition;
        void main() {
          vec3 normal = normalize(vNormal);
          vec3 lightDirection = normalize(vec3(0.45, 0.8, 1.0));
          float diffuse = max(dot(normal, lightDirection), 0.0);
          vec3 viewDirection = normalize(vec3(0.0, 0.2, 8.5) - vWorldPosition);
          float rim = pow(1.0 - max(dot(normal, viewDirection), 0.0), 2.2);
          vec3 color = uColor * (0.24 + 0.76 * diffuse + uGlow) + uColor * rim * 0.42;
          gl_FragColor = vec4(color, 1.0);
        }
      `);
      const program = this.gl.createProgram();
      this.gl.attachShader(program, vertex);
      this.gl.attachShader(program, fragment);
      this.gl.linkProgram(program);
      if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) {
        throw new Error(this.gl.getProgramInfoLog(program) || "Unable to link WebGL program");
      }
      return program;
    }

    uploadMesh(data) {
      const position = this.gl.createBuffer();
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, position);
      this.gl.bufferData(this.gl.ARRAY_BUFFER, new Float32Array(data.positions), this.gl.STATIC_DRAW);

      const normal = this.gl.createBuffer();
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, normal);
      this.gl.bufferData(this.gl.ARRAY_BUFFER, new Float32Array(data.normals), this.gl.STATIC_DRAW);

      const index = this.gl.createBuffer();
      this.gl.bindBuffer(this.gl.ELEMENT_ARRAY_BUFFER, index);
      this.gl.bufferData(this.gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(data.indices), this.gl.STATIC_DRAW);
      return { position, normal, index, count: data.indices.length };
    }

    bindEvents() {
      this.canvas.addEventListener("pointermove", (event) => {
        const bounds = this.canvas.getBoundingClientRect();
        this.pointerTarget[0] = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2;
        this.pointerTarget[1] = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2;
      });
      this.canvas.addEventListener("pointerleave", () => {
        this.pointerTarget[0] = 0;
        this.pointerTarget[1] = 0;
      });
      this.canvas.addEventListener("webglcontextlost", (event) => {
        event.preventDefault();
        this.host.classList.add("webgl-unavailable");
      });
    }

    setMood(name) {
      this.moodName = this.moods[name] ? name : "focused";
    }

    setSpeaking(speaking) {
      this.speaking = Boolean(speaking);
    }

    resize() {
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.floor(this.canvas.clientWidth * pixelRatio));
      const height = Math.max(1, Math.floor(this.canvas.clientHeight * pixelRatio));
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      this.gl.viewport(0, 0, width, height);
      const projection = M4.perspective(Math.PI / 5.2, width / height, 0.1, 50);
      const view = M4.translation(0, -0.05, -8.5);
      this.viewProjection = M4.multiply(projection, view);
    }

    draw(meshName, world, color, glow = 0.08) {
      const mesh = this.meshes[meshName];
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, mesh.position);
      this.gl.enableVertexAttribArray(this.locations.position);
      this.gl.vertexAttribPointer(this.locations.position, 3, this.gl.FLOAT, false, 0, 0);
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, mesh.normal);
      this.gl.enableVertexAttribArray(this.locations.normal);
      this.gl.vertexAttribPointer(this.locations.normal, 3, this.gl.FLOAT, false, 0, 0);
      this.gl.bindBuffer(this.gl.ELEMENT_ARRAY_BUFFER, mesh.index);
      this.gl.uniformMatrix4fv(this.locations.world, false, new Float32Array(world));
      this.gl.uniform3fv(this.locations.color, new Float32Array(hexToRgb(color)));
      this.gl.uniform1f(this.locations.glow, glow);
      this.gl.drawElements(this.gl.TRIANGLES, mesh.count, this.gl.UNSIGNED_SHORT, 0);
    }

    drawPart(character, mesh, position, rotation, scale, color, glow = 0.08) {
      const local = M4.compose(position, rotation, scale);
      this.draw(mesh, M4.multiply(character, local), color, glow);
    }

    drawCylinderBetween(character, start, end, radius, color, glow = 0.08) {
      const direction = [end[0] - start[0], end[1] - start[1], end[2] - start[2]];
      const length = Math.hypot(direction[0], direction[1], direction[2]);
      const yAxis = normalize(direction);
      let xAxis = cross([0, 0, 1], yAxis);
      if (Math.hypot(xAxis[0], xAxis[1], xAxis[2]) < 0.001) xAxis = cross([1, 0, 0], yAxis);
      xAxis = normalize(xAxis);
      const zAxis = normalize(cross(yAxis, xAxis));
      const midpoint = [
        (start[0] + end[0]) / 2,
        (start[1] + end[1]) / 2,
        (start[2] + end[2]) / 2,
      ];
      const local = [
        xAxis[0] * radius, xAxis[1] * radius, xAxis[2] * radius, 0,
        yAxis[0] * length, yAxis[1] * length, yAxis[2] * length, 0,
        zAxis[0] * radius, zAxis[1] * radius, zAxis[2] * radius, 0,
        midpoint[0], midpoint[1], midpoint[2], 1,
      ];
      this.draw("cylinder", M4.multiply(character, local), color, glow);
    }

    drawScene(time) {
      const mood = this.moods[this.moodName];
      const animation = this.reduceMotion ? 0 : time;
      const bob = Math.sin(animation * 1.7) * 0.055;
      const idleYaw = Math.sin(animation * 0.55) * 0.08;
      const yaw = idleYaw + this.pointer[0] * 0.22;
      const pitch = -0.04 + this.pointer[1] * 0.12;
      let character = M4.translation(0, bob - 0.02, 0);
      character = M4.multiply(character, M4.rotationY(yaw));
      character = M4.multiply(character, M4.rotationX(pitch));

      const dark = 0x102b43;
      const pale = 0xc9f8f1;
      const face = 0xeafffb;
      const feature = 0x173850;

      this.drawPart(character, "sphere", [0, -0.78, -0.08], [0, 0, 0], [0.82, 1.34, 0.66], dark, 0.02);

      const strandPoints = [[], []];
      const nodes = 34;
      for (let strand = 0; strand < 2; strand += 1) {
        const phase = strand * Math.PI;
        const color = strand === 0 ? mood.primary : mood.secondary;
        for (let index = 0; index < nodes; index += 1) {
          const t = index / (nodes - 1);
          const angle = t * Math.PI * 2 * 1.12 + phase + animation * 0.12;
          const taper = 0.87 + Math.sin(t * Math.PI) * 0.13;
          const point = [
            Math.sin(angle) * 1.02 * taper,
            0.92 - t * 3.25,
            Math.cos(angle) * 0.37,
          ];
          strandPoints[strand].push(point);
          this.drawPart(character, "sphere", point, [0, 0, 0], [0.18, 0.18, 0.18], color, 0.2);
        }
      }

      for (let index = 7; index < nodes; index += 5) {
        this.drawCylinderBetween(character, strandPoints[0][index], strandPoints[1][index], 0.045, pale, 0.12);
      }

      this.drawPart(character, "sphere", [0, 1.32, 0.04], [0, 0, 0], [1.01, 0.94, 0.82], dark, 0.03);
      this.drawPart(character, "torus", [0, 1.32, 0.48], [0, 0, 0], [0.96, 0.9, 0.96], mood.primary, 0.18);
      this.drawPart(character, "sphere", [0, 1.3, 0.69], [0, 0, 0], [0.77, 0.68, 0.14], face, 0.12);

      this.drawPart(character, "cylinder", [-0.98, 1.3, 0.02], [0, 0, Math.PI / 2], [0.22, 0.22, 0.22], mood.primary, 0.15);
      this.drawPart(character, "cylinder", [0.98, 1.3, 0.02], [0, 0, Math.PI / 2], [0.22, 0.22, 0.22], mood.secondary, 0.15);

      const leftAntenna = [[-0.42, 1.95, 0.02], [-0.72, 2.58, 0.12]];
      const rightAntenna = [[0.42, 1.95, 0.02], [0.72, 2.58, 0.12]];
      this.drawCylinderBetween(character, leftAntenna[0], leftAntenna[1], 0.055, mood.primary, 0.22);
      this.drawCylinderBetween(character, rightAntenna[0], rightAntenna[1], 0.055, mood.secondary, 0.22);
      this.drawPart(character, "sphere", leftAntenna[1], [0, 0, 0], [0.13, 0.13, 0.13], mood.accent, 0.42);
      this.drawPart(character, "sphere", rightAntenna[1], [0, 0, 0], [0.13, 0.13, 0.13], mood.secondary, 0.35);

      const blinkPhase = animation % 4.7;
      const blink = blinkPhase > 4.55 ? 0.14 : 1;
      for (const side of [-1, 1]) {
        this.drawPart(
          character,
          "sphere",
          [side * 0.3, 1.47, 0.84],
          [0, 0, side * 0.08],
          [0.13, 0.16 * blink, 0.05],
          feature,
          0,
        );
      }

      const mouthOpen = this.speaking ? 0.1 + Math.abs(Math.sin(animation * 9)) * 0.08 : 0.055;
      for (let index = 0; index < 7; index += 1) {
        const t = index / 6;
        const x = -0.31 + t * 0.62;
        const y = 1.1 - Math.sin(t * Math.PI) * 0.13;
        this.drawPart(character, "sphere", [x, y, 0.86], [0, 0, 0], [0.065, mouthOpen, 0.035], feature, 0);
      }

      this.drawPart(character, "torus", [0, -0.58, 0.62], [0, 0, 0], [0.3, 0.3, 0.3], mood.primary, 0.26);
      this.drawPart(character, "sphere", [0, -0.58, 0.7], [0, 0, 0], [0.19, 0.19, 0.08], mood.accent, 0.42);

      const ringRotation = animation * 0.16;
      this.drawPart(character, "torus", [0, -0.55, -0.4], [1.18, 0.2, ringRotation], [1.42, 1.42, 1.42], mood.primary, 0.32);
      this.drawPart(character, "torus", [0, -0.55, -0.45], [1.08, -0.22, -ringRotation], [1.25, 1.25, 1.25], mood.secondary, 0.28);
    }

    render(timestamp) {
      this.resize();
      this.pointer[0] += (this.pointerTarget[0] - this.pointer[0]) * 0.065;
      this.pointer[1] += (this.pointerTarget[1] - this.pointer[1]) * 0.065;
      this.gl.clear(this.gl.COLOR_BUFFER_BIT | this.gl.DEPTH_BUFFER_BIT);
      this.gl.useProgram(this.program);
      this.gl.uniformMatrix4fv(this.locations.viewProjection, false, new Float32Array(this.viewProjection));
      this.drawScene((timestamp - this.startTime) / 1000);
      window.requestAnimationFrame(this.render);
    }
  }

  const canvas = document.getElementById("helix-3d-canvas");
  if (!canvas) return;
  try {
    window.helixMascot = new HelixMascot(canvas);
  } catch (error) {
    console.error("Unable to initialize the local WebGL mascot", error);
    const host = canvas.closest(".helix-avatar");
    if (host) host.classList.add("webgl-unavailable");
  }
}());
