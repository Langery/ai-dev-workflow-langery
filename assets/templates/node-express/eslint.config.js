// ESLint 9 Flat Config
// 文档：https://eslint.org/docs/latest/use/configure/configuration-files
import js from '@eslint/js';
import globals from 'globals';

export default [
  // 基础推荐规则
  js.configs.recommended,

  // 全局配置
  {
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: 'module', // ES Modules
      globals: {
        ...globals.node,
        ...globals.es2024,
      },
    },
  },

  // 项目通用规则
  {
    rules: {
      // 错误
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-var': 'error',
      'prefer-const': 'error',
      'eqeqeq': ['error', 'always'],

      // 风格（交给 Prettier 管，这里轻量约束）
      'prefer-arrow-callback': 'warn',
      'prefer-template': 'warn',

      // 异步相关（防 unhandled rejection）
      'no-async-promise-executor': 'error',
      'require-await': 'warn',
      'no-return-await': 'error',
    },
  },

  // 测试文件特殊规则
  {
    files: ['tests/**/*.test.js', 'tests/**/*.spec.js'],
    languageOptions: {
      globals: {
        ...globals.jest,
        describe: 'readonly',
        it: 'readonly',
        test: 'readonly',
        expect: 'readonly',
        beforeEach: 'readonly',
        afterEach: 'readonly',
        beforeAll: 'readonly',
        afterAll: 'readonly',
      },
    },
    rules: {
      'no-console': 'off',
    },
  },

  // 忽略目录
  {
    ignores: ['node_modules/', 'dist/', 'coverage/', '*.config.js'],
  },
];
