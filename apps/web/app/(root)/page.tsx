import { PickLanguage } from './pick-language';

/** `/` has no language: send the user to the one they last chose, English otherwise. */
export default function Root() {
  return <PickLanguage />;
}
