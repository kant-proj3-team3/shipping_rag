// 공통 ESLint 규칙 (모든 React 프로젝트). 프로젝트 루트의 eslint.config.mjs 가 이 파일을 읽어 플러그인과 묶는다.
// Next.js 프로젝트는 next.mjs, React Native 프로젝트는 react-native.mjs 를 **추가로** 읽는다 (둘 다 이 파일 위에 얹는다).
//
// 이 파일은 규칙 데이터만 export 한다. 플러그인을 import 하지 않는다 — 이 파일이 프로젝트 밖(홈 폴더)에 있을 수 있어
// 프로젝트의 node_modules 를 못 보기 때문이다. 플러그인 등록(plugins: { react, "react-hooks": … })은 eslint.config.mjs 가 한다.
// 그래서 여기 규칙 이름의 접두(react/, react-hooks/, jsx-a11y/, import-x/, @typescript-eslint/)는 거기서 등록하는 이름과 맞아야 한다.
//
// files 패턴은 프로젝트 루트 기준으로 해석된다 (flat config 는 설정 파일 위치 기준). 디렉터리가 들어간 패턴도 여기 둬도 된다.
//
// 코드 규칙과 ESLint 규칙 대응:
//   Rules of React .................. react-hooks/rules-of-hooks, exhaustive-deps + (v6+) purity · refs · immutability ·
//                                     set-state-in-effect 등 컴파일러 규칙. eslint.config.mjs 가 reactHooks.configs.flat.recommended 로 켠다
//   함수 컴포넌트 · 선언문 ........... react/function-component-definition, react/no-unstable-nested-components
//   named export 만 ................. import-x/no-default-export (files.defaultExportAllowed 에서 해제)
//   조건부 렌더 {count && …} ........ react/jsx-no-leaked-render
//   key · fragment · boolean prop ... react/jsx-key, jsx-no-useless-fragment, jsx-boolean-value, no-array-index-key
//   context value 객체 리터럴 ....... react/jsx-no-constructed-context-values
//   [x, setX] 이름 ................... react/hook-use-state
//   타입 ............................ @typescript-eslint/* (tsRules) — interface 우선, any · ! · @ts-ignore 금지, import type
//   이름 규칙 ........................ @typescript-eslint/naming-convention
//   === · {} · var · console ........ eqeqeq, curly, no-var, no-console
//   import 순서 · 순환 .............. import-x/order, import-x/no-cycle
//   포맷 ............................ 전부 Prettier. eslint.config.mjs 가 eslint-config-prettier 를 마지막에 둔다

export const ignores = [
  "node_modules/**",
  "dist/**",
  "build/**",
  "out/**",
  ".next/**",
  ".expo/**",
  "coverage/**",
  "android/**",
  "ios/**",
  "**/*.generated.*",
  "**/_generated/**",
  "**/*.d.ts",
];

export const files = {
  // 모든 소스
  source: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
  // TS 규칙(tsRules)을 거는 파일
  ts: ["**/*.{ts,tsx,mts,cts}"],
  // 컴포넌트 파일 — tsxRules (반환 타입 생략 허용)
  tsx: ["**/*.tsx"],
  // JS 프로젝트에서 jsRules 를 거는 파일
  js: ["**/*.{js,jsx,mjs,cjs}"],
  // 앱 진입점 — entryRules (document.getElementById("root")! 한 줄 허용)
  entry: ["main.{ts,tsx}", "src/main.{ts,tsx}", "index.{ts,tsx}", "src/index.{ts,tsx}"],
  // 테스트 · 스토리 — 완화 규칙(testRules)
  test: [
    "**/*.{test,spec}.{js,jsx,ts,tsx}",
    "**/__tests__/**/*.{js,jsx,ts,tsx}",
    "**/__mocks__/**/*.{js,jsx,ts,tsx}",
    "**/test/**/*.{js,jsx,ts,tsx}",
    "**/*.stories.{js,jsx,ts,tsx}",
  ],
  // 설정 파일 · 스크립트 · 저장소 안 공유 규칙 — 타입 검사 없이, console 허용
  config: [
    "*.config.{js,mjs,cjs,ts,mts}",
    "**/*.config.{js,mjs,cjs,ts,mts}",
    "eslint.config.*",
    ".eslint/**/*.{js,mjs}",
    ".storybook/**/*.{js,mjs,ts,tsx}",
    "scripts/**/*.{js,mjs,ts}",
  ],
  // default export 가 허용되는 파일: 도구 · 프레임워크가 요구하는 것
  // Next.js 라우트 파일은 next.mjs 의 files.defaultExportAllowed 에 따로 있다
  defaultExportAllowed: [
    "*.config.{js,mjs,cjs,ts,mts}",
    "**/*.config.{js,mjs,cjs,ts,mts}",
    "**/*.stories.{js,jsx,ts,tsx}",
    "**/*.d.ts",
    "eslint.config.*",
    "vite.config.*",
    "vitest.config.*",
    "playwright.config.*",
    "tailwind.config.*",
    "postcss.config.*",
    "babel.config.*",
    "metro.config.*",
    "app.config.*",
    ".storybook/**",
    "**/*.cjs",
  ],
};

// ---------------------------------------------------------------------------
// 모든 소스 파일 (JS · TS 공통)
// ---------------------------------------------------------------------------
export const rules = {
  // --- 일반 JS ---
  eqeqeq: ["error", "always", { null: "ignore" }], // === 만. x == null 은 null · undefined 를 한 번에 볼 때 허용
  curly: ["error", "all"],
  "no-var": "error",
  "prefer-const": ["error", { destructuring: "all" }],
  "prefer-template": "error",
  "prefer-arrow-callback": "error",
  "prefer-rest-params": "error",
  "prefer-spread": "error",
  "object-shorthand": ["error", "always"],
  "no-nested-ternary": "error",
  "no-unneeded-ternary": "error",
  "no-else-return": ["error", { allowElseIf: false }],
  "no-lonely-if": "error",
  // immer draft · reduce acc 는 허용
  "no-param-reassign": [
    "error",
    { props: true, ignorePropertyModificationsFor: ["draft", "acc", "state", "ref"] },
  ],
  "no-console": ["error", { allow: ["warn", "error"] }], // 로거를 쓴다. warn · error 는 로거가 없는 프로젝트용
  "no-debugger": "error",
  "no-alert": "error",
  "no-eval": "error",
  "no-implied-eval": "error",
  "no-new-func": "error",
  "no-new-wrappers": "error",
  "no-throw-literal": "error", // TS 파일에서는 tsRules 의 only-throw-error 가 대신한다
  "no-return-assign": "error",
  "no-sequences": "error",
  "no-unused-expressions": ["error", { allowShortCircuit: true, allowTernary: false }],
  "no-restricted-syntax": [
    "error",
    {
      selector: "ForInStatement",
      message: "for…in 은 프로토타입 키가 섞인다. Object.keys · entries 로.",
    },
    { selector: "LabeledStatement", message: "label 은 쓰지 않는다." },
    { selector: "WithStatement", message: "with 는 쓰지 않는다." },
    {
      selector: "TSEnumDeclaration[const=true]",
      message: "const enum 은 쓰지 않는다 (isolatedModules). 문자열 유니온 또는 as const 객체.",
    },
  ],
  "no-restricted-globals": [
    "error",
    { name: "isNaN", message: "Number.isNaN" },
    { name: "isFinite", message: "Number.isFinite" },
    { name: "event", message: "핸들러 인자로 받는다." },
  ],

  // --- import ---
  "import-x/no-default-export": "error", // files.defaultExportAllowed 에서 해제
  "import-x/no-cycle": ["error", { maxDepth: 4, ignoreExternal: true }], // 외부 패키지 안 순환은 우리 문제가 아니다 (파싱 비용도 크다)
  "import-x/no-self-import": "error",
  "import-x/no-useless-path-segments": ["error", { noUselessIndex: true }],
  "import-x/no-duplicates": ["error", { "prefer-inline": true }],
  "import-x/first": "error",
  "import-x/newline-after-import": "error",
  "import-x/no-mutable-exports": "error", // export let 금지
  "import-x/no-named-as-default-member": "off", // 서드파티 CJS 패키지에서 오탐
  "import-x/default": "off", // TS 가 검사한다. esModuleInterop 설정에 따라 오탐
  "import-x/order": [
    "error",
    {
      // "type" 그룹을 따로 두지 않는다 — `import type` 문도 경로 그룹 안에서 정렬된다
      groups: ["builtin", "external", "internal", ["parent", "sibling", "index"]],
      pathGroups: [{ pattern: "@/**", group: "internal", position: "after" }],
      pathGroupsExcludedImportTypes: ["builtin"],
      "newlines-between": "always",
      alphabetize: { order: "asc", caseInsensitive: true },
    },
  ],

  // --- React (플러그인 recommended 위에 얹는 것) ---
  "react/react-in-jsx-scope": "off", // 새 JSX 변환. React 17+
  "react/prop-types": "off", // TS 가 한다. JS 프로젝트는 jsRules 에서 다시 켠다
  "react/jsx-filename-extension": ["error", { extensions: [".jsx", ".tsx"] }],
  "react/function-component-definition": [
    "error",
    { namedComponents: "function-declaration", unnamedComponents: "arrow-function" },
  ],
  "react/no-unstable-nested-components": ["error", { allowAsProps: true }], // render prop 으로 넘기는 건 허용
  "react/jsx-key": [
    "error",
    { checkFragmentShorthand: true, checkKeyMustBeforeSpread: true, warnOnDuplicates: true },
  ],
  "react/no-array-index-key": "warn", // 정적 목록에선 허용 — 이유 주석과 함께 disable
  "react/jsx-no-useless-fragment": ["error", { allowExpressions: true }],
  "react/jsx-fragments": ["error", "syntax"],
  "react/jsx-boolean-value": ["error", "never"],
  "react/jsx-curly-brace-presence": [
    "error",
    { props: "never", children: "never", propElementValues: "always" },
  ],
  "react/jsx-no-leaked-render": ["error", { validStrategies: ["coerce", "ternary"] }], // {count && …} 금지
  "react/jsx-no-constructed-context-values": "error",
  "react/jsx-pascal-case": ["error", { allowNamespace: true }],
  "react/jsx-no-target-blank": ["error", { enforceDynamicLinks: "always" }],
  "react/jsx-no-script-url": "error",
  "react/self-closing-comp": "error",
  "react/hook-use-state": ["error", { allowDestructuredState: true }], // [x, setX]
  "react/no-object-type-as-default-prop": "error",
  "react/no-danger": "warn",
  "react/no-unknown-property": "error",
  "react/button-has-type": "error",
  "react/void-dom-elements-no-children": "error",
  "react/no-this-in-sfc": "error",
  "react/no-access-state-in-setstate": "error",
  "react/no-did-mount-set-state": "error",
  "react/no-did-update-set-state": "error",
  "react/prefer-stateless-function": "error", // 클래스 컴포넌트는 Error Boundary 만
  "react/display-name": "off", // 함수 선언문을 쓰므로 이름이 항상 있다
  "react/require-default-props": "off", // TS 기본값은 구조 분해에서
  "react/jsx-props-no-spreading": "off", // {...rest} 전달은 허용
  "react/destructuring-assignment": "off", // props 전달 패턴에서 오탐이 많다. 시그니처 구조 분해는 리뷰로

  // --- React Hooks: eslint.config.mjs 가 reactHooks.configs.flat.recommended 를 켠다. 여기서는 수위만 올린다 ---
  "react-hooks/rules-of-hooks": "error",
  "react-hooks/exhaustive-deps": "error", // recommended 는 warn. 의존성 누락은 버그다 — 일부러 빼면 disable + 이유
};

// ---------------------------------------------------------------------------
// TS 파일 (typescript-eslint recommendedTypeChecked 위에 얹는 것)
// ---------------------------------------------------------------------------
export const tsRules = {
  // JS 규칙 중 TS 버전이 있는 것은 TS 버전으로 바꾼다
  "no-throw-literal": "off",
  "@typescript-eslint/only-throw-error": "error",
  "no-unused-vars": "off",
  "@typescript-eslint/no-unused-vars": [
    "error",
    {
      args: "after-used",
      argsIgnorePattern: "^_", // 시그니처 맞춤용 미사용 인자만 _ 접두
      varsIgnorePattern: "^_",
      caughtErrors: "all",
      caughtErrorsIgnorePattern: "^_",
      destructuredArrayIgnorePattern: "^_",
      ignoreRestSiblings: true, // const { password, ...safe } = user
    },
  ],
  "no-unused-expressions": "off",
  "@typescript-eslint/no-unused-expressions": [
    "error",
    { allowShortCircuit: true, allowTernary: false },
  ],
  "no-use-before-define": "off",
  "@typescript-eslint/no-use-before-define": [
    "error",
    { functions: false, classes: true, variables: true, typedefs: false },
  ],
  "no-shadow": "off",
  "@typescript-eslint/no-shadow": ["error", { ignoreTypeValueShadow: true }],
  "require-await": "off",
  "@typescript-eslint/require-await": "error",
  "no-return-await": "off",
  "@typescript-eslint/return-await": ["error", "in-try-catch"],

  // --- 타입 ---
  "@typescript-eslint/consistent-type-definitions": ["error", "interface"], // 객체 모양은 interface
  "@typescript-eslint/array-type": ["error", { default: "array-simple", readonly: "array-simple" }], // T[] / Array<복합>
  "@typescript-eslint/consistent-type-imports": [
    "error",
    { prefer: "type-imports", fixStyle: "inline-type-imports", disallowTypeAnnotations: true },
  ],
  "@typescript-eslint/consistent-type-exports": [
    "error",
    { fixMixedExportsWithInlineTypeSpecifier: true },
  ],
  "@typescript-eslint/no-import-type-side-effects": "error",
  "@typescript-eslint/no-explicit-any": ["error", { fixToUnknown: true, ignoreRestArgs: false }],
  "@typescript-eslint/no-unsafe-argument": "error",
  "@typescript-eslint/no-unsafe-assignment": "error",
  "@typescript-eslint/no-unsafe-call": "error",
  "@typescript-eslint/no-unsafe-member-access": "error",
  "@typescript-eslint/no-unsafe-return": "error",
  "@typescript-eslint/no-non-null-assertion": "error", // 앱 진입점은 entryRules 에서 해제
  "@typescript-eslint/no-non-null-asserted-optional-chain": "error",
  "@typescript-eslint/no-namespace": "error",
  "@typescript-eslint/no-require-imports": "error",
  "@typescript-eslint/no-wrapper-object-types": "error", // String · Number · Object
  "@typescript-eslint/no-empty-object-type": ["error", { allowInterfaces: "with-single-extends" }],
  "@typescript-eslint/no-unsafe-function-type": "error",
  "@typescript-eslint/ban-ts-comment": [
    "error",
    {
      "ts-ignore": true,
      "ts-nocheck": true,
      "ts-check": false,
      "ts-expect-error": "allow-with-description",
      minimumDescriptionLength: 8,
    },
  ],
  // export 함수는 반환 타입. 컴포넌트 파일(.tsx)은 tsxRules 에서 해제
  "@typescript-eslint/explicit-module-boundary-types": [
    "error",
    { allowArgumentsExplicitlyTypedAsAny: false },
  ],
  "@typescript-eslint/explicit-member-accessibility": ["error", { accessibility: "no-public" }], // public 은 적지 않는다
  // parameter property(constructor(private readonly x: T))는 tsconfig erasableSyntaxOnly(Vite 기본) 에서 금지된다.
  // 어느 쪽이든 tsc 가 판단하므로 린트는 강제하지 않는다
  "@typescript-eslint/parameter-properties": "off",
  "@typescript-eslint/prefer-readonly": "error",
  "@typescript-eslint/class-literal-property-style": ["error", "fields"],
  "@typescript-eslint/no-extraneous-class": ["error", { allowWithDecorator: false }], // static 만 있는 클래스 → 모듈 함수
  "@typescript-eslint/prefer-nullish-coalescing": [
    "error",
    { ignoreConditionalTests: true, ignorePrimitives: { boolean: true } },
  ],
  "@typescript-eslint/prefer-optional-chain": "error",
  "@typescript-eslint/prefer-as-const": "error",
  "@typescript-eslint/prefer-for-of": "error",
  "@typescript-eslint/prefer-includes": "error",
  "@typescript-eslint/prefer-string-starts-ends-with": "error",
  "@typescript-eslint/prefer-enum-initializers": "error", // enum 을 쓴다면 값은 전부 명시
  "@typescript-eslint/no-inferrable-types": "error",
  "@typescript-eslint/no-unnecessary-type-assertion": "error",
  "@typescript-eslint/no-unnecessary-boolean-literal-compare": "error",
  "@typescript-eslint/no-unnecessary-condition": ["warn", { allowConstantLoopConditions: true }], // noUncheckedIndexedAccess 와 같이 쓰면 정확하다
  "@typescript-eslint/switch-exhaustiveness-check": [
    "error",
    { considerDefaultExhaustiveForUnions: true, requireDefaultForNonUnion: true },
  ],
  "@typescript-eslint/no-floating-promises": ["error", { ignoreVoid: true, ignoreIIFE: true }], // void fn() 으로 의도를 표시
  "@typescript-eslint/no-misused-promises": [
    "error",
    { checksVoidReturn: { attributes: false, arguments: false } }, // onClick={async …} 허용
  ],
  "@typescript-eslint/promise-function-async": "off", // Promise 를 그대로 돌려주는 얇은 래퍼 허용
  "@typescript-eslint/restrict-template-expressions": [
    "error",
    { allowNumber: true, allowBoolean: true, allowNullish: false },
  ],
  "@typescript-eslint/unbound-method": ["error", { ignoreStatic: true }],
  "@typescript-eslint/method-signature-style": ["error", "property"], // interface 메서드는 property 꼴 → strictFunctionTypes 적용
  "@typescript-eslint/no-redundant-type-constituents": "error",
  "@typescript-eslint/no-duplicate-type-constituents": "error",
  "@typescript-eslint/no-confusing-void-expression": [
    "error",
    { ignoreArrowShorthand: true, ignoreVoidOperator: true },
  ],
  "@typescript-eslint/naming-convention": [
    "error",
    // 기본: camelCase. 컴포넌트 · 상수는 아래에서 PascalCase · UPPER_CASE 허용
    {
      selector: "default",
      format: ["camelCase"],
      leadingUnderscore: "allow",
      trailingUnderscore: "forbid",
    },
    { selector: "import", format: null }, // 서드파티 이름은 그대로
    {
      selector: "variable",
      format: ["camelCase", "PascalCase", "UPPER_CASE"], // 컴포넌트 · context · 상수
      leadingUnderscore: "allow",
    },
    { selector: "function", format: ["camelCase", "PascalCase"] }, // 컴포넌트는 PascalCase
    { selector: "parameter", format: ["camelCase", "PascalCase"], leadingUnderscore: "allow" }, // HOC 가 컴포넌트를 받을 때
    { selector: "property", format: null }, // 외부 API 응답 · CSS 속성 · 헤더 이름은 강제하지 않는다. 경계에서 변환한다
    { selector: "objectLiteralMethod", format: ["camelCase"] },
    {
      selector: "classProperty",
      modifiers: ["readonly", "static"],
      format: ["UPPER_CASE", "camelCase"],
    },
    { selector: "typeLike", format: ["PascalCase"] },
    { selector: "interface", format: ["PascalCase"], custom: { regex: "^I[A-Z]", match: false } }, // IFoo 금지
    {
      selector: "typeAlias",
      format: ["PascalCase"],
      custom: { regex: "^T[A-Z][a-z]", match: false }, // TFoo 금지 (TItem 제네릭은 typeParameter)
    },
    { selector: "typeParameter", format: ["PascalCase"] }, // T · TItem · Key
    { selector: "enum", format: ["PascalCase"] },
    { selector: "enumMember", format: ["UPPER_CASE"] },
  ],
};

// ---------------------------------------------------------------------------
// .tsx 파일 — tsRules 위에 얹는 것
// ---------------------------------------------------------------------------
export const tsxRules = {
  // 컴포넌트는 반환 타입을 생략한다. JSX 추론이 정확하고, 이 규칙은 PascalCase 함수만 빼는 옵션이 없다.
  // export 하는 훅 · 유틸은 .ts 파일에 두어 tsRules 가 잡게 한다.
  "@typescript-eslint/explicit-module-boundary-types": "off",
};

// ---------------------------------------------------------------------------
// 앱 진입점 — document.getElementById("root")! 한 줄만 허용
// ---------------------------------------------------------------------------
export const entryRules = {
  "@typescript-eslint/no-non-null-assertion": "off",
};

// ---------------------------------------------------------------------------
// JS 프로젝트 (.jsx) — tsRules 대신 거는 것. 타입이 없으므로 prop-types 를 켠다
// ---------------------------------------------------------------------------
export const jsRules = {
  "react/prop-types": "error",
  "no-unused-vars": [
    "error",
    {
      args: "after-used",
      argsIgnorePattern: "^_",
      varsIgnorePattern: "^_",
      caughtErrors: "all",
      caughtErrorsIgnorePattern: "^_",
      ignoreRestSiblings: true,
    },
  ],
  "no-use-before-define": ["error", { functions: false, classes: true, variables: true }],
  "no-shadow": "error",
  "require-await": "error",
};

// ---------------------------------------------------------------------------
// 테스트 · 스토리 파일 — 완화
// ---------------------------------------------------------------------------
export const testRules = {
  "no-console": "off",
  "import-x/no-default-export": "off", // *.stories 의 meta
  "react/jsx-no-constructed-context-values": "off",
  "react/function-component-definition": "off", // 스토리 · 테스트의 작은 래퍼는 화살표 허용
  "react/no-unstable-nested-components": "off",
  "@typescript-eslint/no-explicit-any": "off",
  "@typescript-eslint/no-non-null-assertion": "off",
  "@typescript-eslint/no-unsafe-argument": "off",
  "@typescript-eslint/no-unsafe-assignment": "off",
  "@typescript-eslint/no-unsafe-call": "off",
  "@typescript-eslint/no-unsafe-member-access": "off",
  "@typescript-eslint/no-unsafe-return": "off",
  "@typescript-eslint/unbound-method": "off", // expect(mock.method)
  "@typescript-eslint/explicit-module-boundary-types": "off",
  "@typescript-eslint/no-empty-function": "off", // vi.fn(() => {})
  "@typescript-eslint/require-await": "off",
  "@typescript-eslint/no-floating-promises": "error", // 테스트에서도 await 빠진 expect 는 버그
};

// ---------------------------------------------------------------------------
// 설정 파일 · 스크립트 — console 허용, default export 허용. 타입 검사 해제는 eslint.config.mjs 가 한다
// ---------------------------------------------------------------------------
export const configRules = {
  "no-console": "off",
  "import-x/no-default-export": "off",
};
