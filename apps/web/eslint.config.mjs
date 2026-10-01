import next from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
    // src/, test/ and build.sh are the Phase 1 dashboard (live until this app reaches parity).
    {
        ignores: [
            'src/**',
            'test/**',
            'dist/**',
            'artifact/**',
            'out/**',
            '.next/**',
            'next-env.d.ts',
            'lib/api/schema.gen.ts',
        ],
    },
    ...next,
    ...nextTs,
];

export default config;
