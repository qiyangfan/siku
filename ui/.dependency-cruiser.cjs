module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-orphans",
      severity: "error",
      // vite-env.d.ts 是三斜线类型引用文件，无 import 属正常形态
      from: { orphan: true, pathNot: ["^src/vite-env\\.d\\.ts$"] },
      to: {},
    },
    {
      name: "no-dev",
      severity: "error",
      from: { pathNot: ["^src/"] },
      to: { dependencyTypes: ["npm-dev"] },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    exclude: { path: "(^|/)(dist|coverage)/" },
  },
};
