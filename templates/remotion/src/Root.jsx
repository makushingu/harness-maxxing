// One <Composition> per video. Edit Intro.jsx, then: npm run still (check one frame) / npm run render.
import { Composition } from 'remotion'
import { Intro } from './Intro'

export const Root = () => (
  <>
    {/* 1920x1080 landscape; use 1080x1920 for shorts / stories, 1080x1080 for square posts */}
    <Composition id="Intro" component={Intro} durationInFrames={150} fps={30} width={1920} height={1080}
      defaultProps={{ title: 'Your title here', subtitle: 'Made with Remotion on your server' }} />
  </>
)
