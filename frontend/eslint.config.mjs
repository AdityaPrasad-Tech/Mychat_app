import tseslint from "typescript-eslint";
export default [
  { ignores: [".next/**", "next-env.d.ts"] },
  ...tseslint.configs.recommended,
];
