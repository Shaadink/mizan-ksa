//-----------------------------------------------------------------------
// <copyright company="Microsoft Corporation">
//        Copyright (c) Microsoft Corporation.  All rights reserved.
//        Licensed under the MIT license. See LICENSE file in the project root for full license information.
// </copyright>
//-----------------------------------------------------------------------

import "@testing-library/jest-dom";

// Windows only: Vite's module runner evaluates spec files under a file:// URL whose drive letter it spells
// itself, while the vitest CLI loads its own modules under the drive letter the shell's working directory
// used. Node treats file:///D:/x and file:///d:/x as different modules, so @vitest/runner gets loaded twice
// and every describe() throws "Cannot read properties of undefined (reading 'config')" with nothing to show
// why. Turn that into the instruction instead. See HONESTY.md row 28.
const here = import.meta.url.match(/^file:\/\/\/([A-Za-z]):/)?.[1];
const cwd = process.cwd().match(/^([A-Za-z]):/)?.[1];
if (here && cwd && here !== cwd) {
    throw new Error(
        `vitest was started from a working directory spelled "${cwd}:" but is loading modules from "${here}:". ` +
        `Node loads those as two separate copies of @vitest/runner and every describe() fails. ` +
        `Re-run from "${here}:" -- e.g. cd ${here}:/mizan-ksa/apps/command-center.`,
    );
}
