// ESLint 설정 (flat config). 공유 규칙은 .eslint/base.mjs 에 있고, 플러그인 등록은 여기서 한다.

import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import prettier from "eslint-config-prettier";
import { createTypeScriptImportResolver } from "eslint-import-resolver-typescript";
import { importX } from "eslint-plugin-import-x";
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

import * as base from "./.eslint/base.mjs";

export default defineConfig([
  globalIgnores(base.ignores),

  // ---- 기본 규칙 세트 (플러그인 recommended) ----
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  react.configs.flat.recommended,
  react.configs.flat["jsx-runtime"],
  reactHooks.configs.flat.recommended,
  jsxA11y.flatConfigs.recommended,
  importX.flatConfigs.recommended,
  importX.flatConfigs.typescript,

  // ---- 공통 settings · parser ----
  {
    files: base.files.source,
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      react: { version: "detect" },
      "import-x/resolver-next": [
        createTypeScriptImportResolver({ alwaysTryTypes: true, project: "./tsconfig.json" }),
      ],
    },
  },

  // ---- 공유 규칙 ----
  { files: base.files.source, rules: base.rules },
  { files: base.files.ts, rules: base.tsRules },
  { files: base.files.tsx, rules: base.tsxRules },
  { files: base.files.entry, rules: base.entryRules },
  { files: base.files.test, rules: base.testRules },
  { files: base.files.defaultExportAllowed, rules: { "import-x/no-default-export": "off" } },

  // ---- 설정 파일 · .eslint/: 타입 검사 없이 ----
  {
    files: base.files.config,
    ...tseslint.configs.disableTypeChecked,
    rules: { ...tseslint.configs.disableTypeChecked.rules, ...base.configRules },
  },

  // ---- Prettier: 포맷 관련 규칙을 전부 끈다. 공유 규칙보다 뒤에 둔다 ----
  prettier,

  // ---- prettier 가 함께 끈 curly 를 되살린다. "all" 은 Prettier 포맷과 부딪히지 않는다 ----
  { files: base.files.source, rules: { curly: base.rules.curly } },
]);
